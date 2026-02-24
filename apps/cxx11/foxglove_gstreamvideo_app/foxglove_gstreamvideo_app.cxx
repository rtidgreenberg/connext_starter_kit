/*
 * (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
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
#include <thread>
#include <chrono>
#include <atomic>
#include <vector>

// include both the standard APIs and extensions
#include <rti/rti.hpp>
#include <rti/core/cond/AsyncWaitSet.hpp>
#include <rti/distlogger/DistLogger.hpp>
#include <rti/config/Logger.hpp>

#include <gst/gst.h>
#include <gst/app/gstappsink.h>
//
// For more information about the headers and namespaces, see:
//    https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/api/connext_dds/api_cpp2/group__DDSNamespaceModule.html
// For information on how to use extensions, see:
//    https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/api/connext_dds/api_cpp2/group__DDSCpp2Conventions.html

#include "application.hpp"  // for command line parsing and ctrl-c
#include "ExampleTypes.hpp"
#include "Definitions.hpp"
#include "DDSParticipantSetup.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"
#include "CompressedVideo.hpp"

// For example legibility.
using namespace rti::all;
using namespace rti::dist_logger;

constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;
const std::string APP_NAME = "FoxgloveGstreamer";

// Image dimensions for large data transfer
constexpr uint32_t IMAGE_WIDTH = 640;
constexpr uint32_t IMAGE_HEIGHT = 480;
constexpr uint32_t IMAGE_SIZE = IMAGE_WIDTH * IMAGE_HEIGHT * 3;  // RGB format
                                                                 // (~900 KB)


void process_video_data(dds::sub::DataReader<::foxglove::CompressedVideo> reader)
{
    auto samples = reader.take();
    for (const auto &sample : samples) {
        // Check if message is not DDS metadata
        if (sample.info().valid()) {
            const auto &image = sample.data();

            // Do something with data message
            std::cout << "[IMAGE_SUBSCRIBER] Image Received:" << std::endl;
            std::cout << "  Image ID: " << image.frame_id() << std::endl;
            std::cout << "  Format: " << image.format() << std::endl;
            std::cout << "  Data Size: " << image.data().size() << " bytes"
                      << std::endl;

            // overloaded -> operator to use RTI extension
            std::cout << "  Topic: " << reader->topic_name() << std::endl;
        }
    }
}

// GStreamer video publisher using test video source
class GStreamerVideoPublisher {
public:
    GStreamerVideoPublisher(
        std::shared_ptr<DDSWriterSetup<::foxglove::CompressedVideo>> writer_setup,
        int width, int height, int fps)
        : writer_setup_(std::move(writer_setup))
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
            // foxglove::CompressedVideo(h264) expects Annex-B, 1 frame per message,
            // no B-frames, and SPS/PPS present on keyframes.
            "x264enc tune=zerolatency speed-preset=ultrafast bframes=0 key-int-max=" + std::to_string(fps) + " ! "
            "h264parse config-interval=-1 ! "
            "video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline ! "
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
            writer_setup_->writer().write(data);
            
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
    
    std::shared_ptr<DDSWriterSetup<::foxglove::CompressedVideo>> writer_setup_;
    int width_;
    int height_;
    int fps_;
    unsigned int frame_count_;
    GstElement* pipeline_;
    GstElement* appsink_;
};


void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    auto& rti_logger = rti::config::Logger::instance();

    rti_logger.notice(
            "Large Data application starting...");

    // DDSReaderSetup and DDSWriterSetup are example wrapper classes for your
    // convenience that simplify DDS reader/writer creation and event handling.
    // They manage DataReader/DataWriter lifecycle, attach status conditions to
    // the centralized AsyncWaitSet, and provide convenient methods to register
    // callbacks for DDS events (data_available, subscription_matched,
    // liveliness_changed, etc.)

        // NOTE: LARGE_DATA_SHMEM pins transport to SHMEM-only (remote bridges won't receive samples).
        // Use LARGE_DATA_SHMEM QoS here so UDP transport remains available.
    auto video_reader = std::make_shared<DDSReaderSetup<::foxglove::CompressedVideo>>(
            participant_setup,
            topics::IMAGE_TOPIC,
            qos_profiles::LARGE_DATA_SHMEM);

        // Setup Writer Interface with LARGE_DATA_SHMEM QoS
    auto video_writer = std::make_shared<DDSWriterSetup<::foxglove::CompressedVideo>>(
            participant_setup,
            topics::IMAGE_TOPIC,
            qos_profiles::LARGE_DATA_SHMEM);

    // Enable Asynchronous Event-Driven processing for reader
    video_reader->set_data_available_handler(process_video_data);

    rti_logger.notice(
            "Large Data app is running. Press Ctrl+C to stop.");
    rti_logger.notice(
            "Subscribing to Image messages with LARGE_DATA_SHMEM QoS...");
    rti_logger.notice(
            "Publishing Image messages with LARGE_DATA_SHMEM QoS...");

    // Initialize GStreamer video publisher (320x240 resolution, 30fps)
    GStreamerVideoPublisher gst_publisher(video_writer, 320, 240, 30);
    
    // Start the pipeline
    gst_publisher.start();
    
    // Run the main loop
    gst_publisher.run_loop();

    rti_logger.notice(
            "Large Data application shutting down...");

    rti_logger.notice("Large Data application stopped");
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

    // Setup and Run the application
    try {
        // Create DDS Participant Setup (creates DomainParticipant and
        // AsyncWaitSet) DDSParticipantSetup is an example wrapper class for
        // your convenience that manages the DDS infrastructure: creates the
        // participant in the specified domain, sets up the AsyncWaitSet with a
        // configurable thread pool for event-driven processing, loads QoS
        // profiles from the XML file, and stores them for use by
        // readers/writers
        auto participant_setup = std::make_shared<DDSParticipantSetup>(
                arguments.domain_id,
                ASYNC_WAITSET_THREADPOOL_SIZE,
                arguments.qos_file_path,
            qos_profiles::DEFAULT_PARTICIPANT,
                APP_NAME);

        // Setup Distributed Logger Singleton
        // This publishes the RTI logs over DDS the network, enabling
        // centralized logging and monitoring across distributed systems.
        // By re-using the application Domain Participant, we optimize the
        // resource usage.

        DistLoggerOptions options;
        options.domain_participant(participant_setup->participant());
        options.application_kind(APP_NAME);
        DistLogger::set_options(options);
        auto &dist_logger = DistLogger::get_instance();

        // Passthrough to configure RTI logger Verbosity.
        // Change Category to display internal Connext logs or user
        //   platform,
        //   communication,
        //   database,
        //   entities,
        //   api,
        //   discovery,
        //   security,
        //   user,
        //   all_categories
        dist_logger.set_verbosity(
                rti::config::LogCategory::user,
                arguments.verbosity);

        // Configure Filter Level. This controls what level gets published
        //   get_fatal_log_level
        //   get_error_log_level
        //   get_warning_log_level
        //   get_notice_log_level
        //   get_info_log_level
        //   get_debug_log_level
        dist_logger.set_filter_level(dist_logger.get_info_log_level());

        // Run
        run(participant_setup);

        // Explicitly finalize DistLogger Singleton
        // before Domain Participant destruction
        DistLogger::get_instance().finalize();
        std::cout << "DistLogger finalized" << std::endl;

    } catch (const std::exception &ex) {
        std::cerr << "Exception: " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

    // Finalize participant factory after all DDS entities are cleaned up
    dds::domain::DomainParticipant::finalize_participant_factory();
    std::cout << "DomainParticipant factory finalized at application exit"
              << std::endl;

    return EXIT_SUCCESS;
}
