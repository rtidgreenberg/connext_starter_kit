/*
* (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
* RTI grants Licensee a license to use, modify, compile, and create derivative
* works of the software solely for use with RTI Connext DDS. Licensee may
* redistribute copies of the software provided that all such copies are subject
* to this license. The software is provided "as is", with no warranty of any
* type, including any warranty for fitness for any purpose. RTI is under no
* obligation to maintain or support the software. RTI shall not be liable for
* any incidental or consequential damages arising out of the use or inability
* to use the software.
*/

#include <iostream>
#include <vector>
#include <cstring>
#include <stdint.h>
#include <memory>

#include <gst/gst.h>
#include <gst/app/gstappsink.h>

#include <dds/pub/ddspub.hpp>
#include <rti/util/util.hpp>
#include <rti/config/Logger.hpp>
#include "application.hpp"
#include "CompressedVideo.hpp"

// GStreamer video publisher using test video source
class GStreamerVideoPublisher {
public:
    GStreamerVideoPublisher(
        dds::pub::DataWriter<::foxglove::CompressedVideo>& writer,
        int width, int height, int fps)
        : writer_(writer)
        , width_(width)
        , height_(height)
        , fps_(fps)
        , frame_count_(0)
        , pipeline_(nullptr)
        , appsink_(nullptr)
    {
        // Initialize GStreamer
        gst_init(nullptr, nullptr);
        
        // Build pipeline: videotestsrc -> videoconvert -> x264enc -> h264parse -> appsink
        // There are numerous test patterns available at https://gstreamer.freedesktop.org/documentation/videotestsrc/index.html?gi-language=c#GstVideoTestSrcPattern
        std::string pipeline_str = 
            "videotestsrc pattern=smpte is-live=true ! "
            "video/x-raw,width=" + std::to_string(width) + 
            ",height=" + std::to_string(height) + 
            ",framerate=" + std::to_string(fps) + "/1 ! "
            "videoconvert ! "
            "x264enc tune=zerolatency speed-preset=ultrafast key-int-max=" + std::to_string(fps) + " ! "
            "video/x-h264,stream-format=byte-stream,profile=baseline ! "
            "h264parse ! "
            "appsink name=sink emit-signals=true sync=false";
        
        std::cout << "Creating GStreamer pipeline: " << pipeline_str << std::endl;
        
        // Create pipeline from description
        GError* error = nullptr;
        pipeline_ = gst_parse_launch(pipeline_str.c_str(), &error);
        if (error != nullptr) {
            std::string err_msg = "Failed to create pipeline: " + std::string(error->message);
            g_error_free(error);
            throw std::runtime_error(err_msg);
        }
        
        // Get appsink element
        appsink_ = gst_bin_get_by_name(GST_BIN(pipeline_), "sink");
        if (!appsink_) {
            throw std::runtime_error("Failed to get appsink element");
        }
        
        // Configure appsink
        g_object_set(G_OBJECT(appsink_), "emit-signals", TRUE, "sync", FALSE, nullptr);
        
        // Connect callback for new samples
        g_signal_connect(appsink_, "new-sample", G_CALLBACK(on_new_sample_static), this);
    }
    
    ~GStreamerVideoPublisher() {
        stop();
        if (appsink_) {
            gst_object_unref(appsink_);
        }
        if (pipeline_) {
            gst_object_unref(pipeline_);
        }
    }
    
    void start() {
        if (gst_element_set_state(pipeline_, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
            throw std::runtime_error("Failed to start pipeline");
        }
        std::cout << "GStreamer pipeline started" << std::endl;
    }
    
    void stop() {
        if (pipeline_) {
            gst_element_set_state(pipeline_, GST_STATE_NULL);
        }
    }
    
    void run_loop() {
        GstBus* bus = gst_element_get_bus(pipeline_);
        
        while (!application::shutdown_requested) {
            // Process messages
            GstMessage* msg = gst_bus_timed_pop_filtered(
                bus, 
                100 * GST_MSECOND,
                static_cast<GstMessageType>(GST_MESSAGE_ERROR | GST_MESSAGE_EOS));
                
            if (msg != nullptr) {
                switch (GST_MESSAGE_TYPE(msg)) {
                    case GST_MESSAGE_ERROR: {
                        GError* err;
                        gchar* debug_info;
                        gst_message_parse_error(msg, &err, &debug_info);
                        std::cerr << "Error: " << err->message << std::endl;
                        if (debug_info) {
                            std::cerr << "Debug: " << debug_info << std::endl;
                        }
                        g_clear_error(&err);
                        g_free(debug_info);
                        gst_message_unref(msg);
                        gst_object_unref(bus);
                        throw std::runtime_error("GStreamer pipeline error");
                    }
                    case GST_MESSAGE_EOS:
                        std::cout << "End of stream" << std::endl;
                        gst_message_unref(msg);
                        gst_object_unref(bus);
                        return;
                    default:
                        break;
                }
                gst_message_unref(msg);
            }
        }
        
        gst_object_unref(bus);
    }
    
private:
    static GstFlowReturn on_new_sample_static(GstElement* sink, gpointer user_data) {
        GStreamerVideoPublisher* self = static_cast<GStreamerVideoPublisher*>(user_data);
        return self->on_new_sample(sink);
    }
    
    GstFlowReturn on_new_sample(GstElement* sink) {
        // Pull sample from appsink
        GstSample* sample = gst_app_sink_pull_sample(GST_APP_SINK(sink));
        if (!sample) {
            std::cerr << "Failed to pull sample" << std::endl;
            return GST_FLOW_ERROR;
        }
        
        // Get buffer from sample
        GstBuffer* buffer = gst_sample_get_buffer(sample);
        if (!buffer) {
            std::cerr << "Failed to get buffer from sample" << std::endl;
            gst_sample_unref(sample);
            return GST_FLOW_ERROR;
        }
        
        // Map buffer for reading
        GstMapInfo map;
        if (!gst_buffer_map(buffer, &map, GST_MAP_READ)) {
            std::cerr << "Failed to map buffer" << std::endl;
            gst_sample_unref(sample);
            return GST_FLOW_ERROR;
        }
        
        try {
            // Create DDS sample
            ::foxglove::CompressedVideo data;
            data.frame_id("camera");
            data.format("h264");
            
            // Set timestamp
            ::foxglove::Time timestamp;
            timestamp.sec(static_cast<int32_t>(frame_count_ / fps_));
            timestamp.nsec((frame_count_ % fps_) * (1000000000 / fps_));
            data.timestamp(timestamp);
            
            // Copy encoded data
            std::vector<uint8_t> encoded_data(map.data, map.data + map.size);
            data.data(encoded_data);
            
            // Write to DDS
            writer_.write(data);
            
            std::cout << "Published frame " << frame_count_ 
                      << " (" << map.size << " bytes)" << std::endl;
            
            frame_count_++;
            
        } catch (const std::exception& ex) {
            std::cerr << "Error publishing frame: " << ex.what() << std::endl;
        }
        
        // Cleanup
        gst_buffer_unmap(buffer, &map);
        gst_sample_unref(sample);
        
        return GST_FLOW_OK;
    }
    
    dds::pub::DataWriter<::foxglove::CompressedVideo>& writer_;
    int width_;
    int height_;
    int fps_;
    unsigned int frame_count_;
    GstElement* pipeline_;
    GstElement* appsink_;
};

void run_publisher_application(unsigned int domain_id)
{
    // DDS objects behave like shared pointers or value types
    dds::domain::DomainParticipant participant(domain_id);

    // Create a Topic with a name and a datatype
    dds::topic::Topic<::foxglove::CompressedVideo> topic(
        participant, "foxglove_CompressedVideo");

    // Create a Publisher
    dds::pub::Publisher publisher(participant);

    // Create a DataWriter with default QoS
    dds::pub::DataWriter<::foxglove::CompressedVideo> writer(publisher, topic);

    // Initialize GStreamer video publisher (320x240 resolution, 30fps)
    GStreamerVideoPublisher gst_publisher(writer, 320, 240, 30);
    
    // Start the pipeline
    gst_publisher.start();
    
    // Run the main loop
    gst_publisher.run_loop();
    
    std::cout << "Publisher finished" << std::endl;
}

int main(int argc, char *argv[])
{

    using namespace application;

    // Parse arguments and handle control-C
    auto arguments = parse_arguments(argc, argv);
    if (arguments.parse_result == ParseReturn::exit) {
        return EXIT_SUCCESS;
    } else if (arguments.parse_result == ParseReturn::failure) {
        return EXIT_FAILURE;
    }
    setup_signal_handlers();

    // Sets Connext verbosity to help debugging
    rti::config::Logger::instance().verbosity(arguments.verbosity);

    try {
        run_publisher_application(arguments.domain_id);
    } catch (const std::exception& ex) {
        // This will catch DDS exceptions
        std::cerr << "Exception in run_publisher_application(): " << ex.what()
        << std::endl;
        return EXIT_FAILURE;
    }

    // Releases the memory used by the participant factory.  Optional at
    // application exit
    dds::domain::DomainParticipant::finalize_participant_factory();

    return EXIT_SUCCESS;
}
