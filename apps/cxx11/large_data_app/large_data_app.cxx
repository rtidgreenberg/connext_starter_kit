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

// For example legibility.
using namespace rti::all;
using namespace rti::dist_logger;

constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;
const std::string APP_NAME = "Large Data CXX APP";

// Image dimensions for large data transfer
constexpr uint32_t IMAGE_WIDTH = 640;
constexpr uint32_t IMAGE_HEIGHT = 480;
constexpr uint32_t IMAGE_SIZE = IMAGE_WIDTH * IMAGE_HEIGHT * 3;  // RGB format (~900 KB)


void process_image_data(dds::sub::DataReader<example_types::Image> reader)
{
    auto samples = reader.take();
    for (const auto& sample : samples)
    {
      // Check if message is not DDS metadata
      if (sample.info().valid())
      {
        const auto& image = sample.data();
        
        // Do something with data message
        std::cout << "[IMAGE_SUBSCRIBER] Image Received:" << std::endl;
        std::cout << "  Image ID: " << image.image_id() << std::endl;
        std::cout << "  Width: " << image.width() << std::endl;
        std::cout << "  Height: " << image.height() << std::endl;
        std::cout << "  Format: " << image.format() << std::endl;
        std::cout << "  Data Size: " << image.data().size() << " bytes" << std::endl;

        // overloaded -> operator to use RTI extension
        std::cout << "  Topic: " << reader->topic_name() << std::endl;
      }
    }
} 


void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    rti::config::Logger::instance().notice("Large Data application starting...");

    // DDSReaderSetup and DDSWriterSetup are example wrapper classes for your convenience that simplify
    // DDS reader/writer creation and event handling. They manage DataReader/DataWriter lifecycle, attach
    // status conditions to the centralized AsyncWaitSet, and provide convenient methods to register
    // callbacks for DDS events (data_available, subscription_matched, liveliness_changed, etc.)

    // Setup Reader Interface with LARGE_DATA_SHMEM QoS
    auto image_reader = std::make_shared<DDSReaderSetup<example_types::Image>>(
        participant_setup,
        topics::IMAGE_TOPIC,
        qos_profiles::LARGE_DATA_SHMEM);

    // Setup Writer Interface with LARGE_DATA_SHMEM QoS
    auto image_writer = std::make_shared<DDSWriterSetup<example_types::Image>>(
        participant_setup,
        topics::IMAGE_TOPIC,
        qos_profiles::LARGE_DATA_SHMEM);

    // Enable Asynchronous Event-Driven processing for reader
    image_reader->set_data_available_handler(process_image_data);

    rti::config::Logger::instance().notice("Large Data app is running. Press Ctrl+C to stop.");
    rti::config::Logger::instance().notice("Subscribing to Image messages with LARGE_DATA_SHMEM QoS...");
    rti::config::Logger::instance().notice("Publishing Image messages with LARGE_DATA_SHMEM QoS...");

    // Initialize image message
    example_types::Image image_msg;
    uint32_t image_count = 0;

    while (!application::shutdown_requested) {

      try
      {
        // Create image ID with zero-padded count
        char image_id_buffer[32];
        snprintf(image_id_buffer, sizeof(image_id_buffer), "img_%06u", image_count);
        
        // Populate image metadata
        image_msg.image_id(image_id_buffer);
        image_msg.width(IMAGE_WIDTH);
        image_msg.height(IMAGE_HEIGHT);
        image_msg.format("RGB");
        
        // Create simulated image data (pattern based on count for variety)
        // In real application, this would be actual camera/sensor data
        std::vector<uint8_t> image_data(IMAGE_SIZE);
        uint8_t pattern_value = static_cast<uint8_t>(image_count % 256);
        std::fill(image_data.begin(), image_data.end(), pattern_value);
        
        image_msg.data(image_data);
        
        // Publish the image
        image_writer->writer().write(image_msg);

        std::cout << "[IMAGE_PUBLISHER] Published Image - ID: " << image_msg.image_id()
                  << ", Size: " << image_msg.data().size() << " bytes"
                  << " (" << IMAGE_WIDTH << "x" << IMAGE_HEIGHT << ")" << std::endl;
        
        rti::config::Logger::instance().notice(("Published Image - id:" + std::string(image_msg.image_id()) 
                    + ", size:" + std::to_string(image_msg.data().size()) + " bytes"
                    + ", " + std::to_string(IMAGE_WIDTH) + "x" + std::to_string(IMAGE_HEIGHT)).c_str());
        
        image_count++;
      }
      catch (const std::exception &ex)
      {
        rti::config::Logger::instance().error(("Failed to publish image: " + std::string(ex.what())).c_str());
      }

      // Alternate Option: Use Polling Method to Read Data
      // Latency contingent on loop rate
      // process_image_data(image_reader->reader());

      // Sleep for 1 second (1 Hz publishing rate)
      std::this_thread::sleep_for(std::chrono::seconds(1));

    }

    rti::config::Logger::instance().notice("Large Data application shutting down...");

    rti::config::Logger::instance().notice("Large Data application stopped");
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
        // Create DDS Participant Setup (creates DomainParticipant and AsyncWaitSet)
        // DDSParticipantSetup is an example wrapper class for your convenience that manages the DDS
        // infrastructure: creates the participant in the specified domain, sets up the AsyncWaitSet with
        // a configurable thread pool for event-driven processing, loads QoS profiles from the XML file,
        // and stores them for use by readers/writers
        auto participant_setup = std::make_shared<DDSParticipantSetup>(
            arguments.domain_id,
            ASYNC_WAITSET_THREADPOOL_SIZE,
            arguments.qos_file_path,
            qos_profiles::LARGE_DATA_PARTICIPANT,
            APP_NAME);
        
        // Setup DistLogger with the shared participant
        // DistLogger provides distributed logging over DDS network. By using the shared participant,
        // all log messages are published to remote subscribers via DDS topics, enabling centralized
        // logging and monitoring across distributed systems. This is more powerful than console logging.
        try {
            DistLoggerOptions options;
            options.domain_participant(participant_setup->participant());
            options.application_kind(APP_NAME);
            
            DistLogger::set_options(options);
            auto& dist_logger = DistLogger::get_instance();
            
            // Configure DistLogger verbosity and filter level for filtering which log messages to publish
            dist_logger.set_verbosity(rti::config::LogCategory::user, arguments.verbosity);
            dist_logger.set_filter_level(dist_logger.get_info_log_level());
            
            rti::config::Logger::instance().notice("DistLogger initialized with shared participant");
            rti::config::Logger::instance().notice(("Using QoS file: " + arguments.qos_file_path).c_str());
            rti::config::Logger::instance().notice("Using QoS profile: LARGE_DATA_PARTICIPANT");
        } catch (const std::exception& ex) {
            std::cerr << "Error initializing DistLogger: " << ex.what() << std::endl;
            throw;
        }
        
        run(participant_setup);
    } catch (const std::exception& ex) {
        // This will catch DDS exceptions
        std::cerr << "Exception in run(): " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

    // Finalize participant factory after all DDSParticipantSetup/DDSReaderSetup/DDSWriterSetup objects are destroyed
    // This should be called at application exit after all DDS entities are cleaned up
    try {
        dds::domain::DomainParticipant::finalize_participant_factory();
        std::cout << "DomainParticipant factory finalized at application exit" << std::endl;
    } catch (const std::exception &e) {
        std::cerr << "Error finalizing participant factory at exit: " << e.what() << std::endl;
    }

    return EXIT_SUCCESS;
}
