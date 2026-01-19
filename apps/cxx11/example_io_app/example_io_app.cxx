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
#include <sstream>
#include <thread>
#include <chrono>
#include <atomic>
#include <ctime>

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
const std::string APP_NAME = "Example CXX IO APP";


void process_command_data(dds::sub::DataReader<example_types::Command> reader)
{
    auto samples = reader.take();
    for (const auto& sample : samples)
    {
      // Check if message is not DDS metadata
      if (sample.info().valid())
      {

        // Do something with data message (logged at DEBUG level)
        std::ostringstream oss;
        oss << sample.data();
        rti::config::Logger::instance().debug(("[COMMAND] " + oss.str()).c_str());

        // overloaded -> operator to use RTI extension
        rti::config::Logger::instance().debug(("[COMMAND] Topic '" + std::string(reader->topic_name()) + "' received").c_str());
      }
    }
}

void on_command_liveliness_changed(dds::sub::DataReader<example_types::Command> reader)
{
    auto status = reader->liveliness_changed_status();
    rti::config::Logger::instance().notice(
        ("[COMMAND] Liveliness changed - alive_count: " +
         std::to_string(status.alive_count()) + ", not_alive_count: " +
         std::to_string(status.not_alive_count())).c_str());
}


void process_button_data(dds::sub::DataReader<example_types::Button> reader)
{
    auto samples = reader.take();
    for (const auto& sample : samples)
    {
      // Check if message is not DDS metadata
      if (sample.info().valid())
      {

        // Do something with data message
        std::ostringstream oss;
        oss << sample.data();
        rti::config::Logger::instance().debug(("[BUTTON] " + oss.str()).c_str());

        // overloaded -> operator to use RTI extension
        rti::config::Logger::instance().debug(("[BUTTON] Topic '" + std::string(reader->topic_name()) + "' received").c_str());
      }
    }
} 

void process_config_data(dds::sub::DataReader<example_types::Config> reader)
{
    auto samples = reader.take();
    for (const auto& sample : samples)
    {
      // Check if message is not DDS metadata
      if (sample.info().valid())
      {

        // Do something with data message
        std::ostringstream oss;
        oss << sample.data();
        rti::config::Logger::instance().debug(("[CONFIG] " + oss.str()).c_str());

        // overloaded -> operator to use RTI extension
        rti::config::Logger::instance().debug(("[CONFIG] Topic '" + std::string(reader->topic_name()) + "' received").c_str());
      }
    }
}

void on_position_publication_matched(dds::pub::DataWriter<example_types::Position> writer)
{
    auto status = writer->publication_matched_status();
    rti::config::Logger::instance().notice(
        ("[POSITION] Publication matched - current_count: " +
         std::to_string(status.current_count()) + ", total_count: " +
         std::to_string(status.total_count())).c_str());
}


void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    rti::config::Logger::instance().notice(("Example I/O application starting on domain " + std::to_string(participant_setup->participant().domain_id())).c_str());

    // DDSReaderSetup and DDSWriterSetup are example wrapper classes for your convenience that simplify
    // DDS reader/writer creation and event handling. They manage DataReader/DataWriter lifecycle, attach
    // status conditions to the centralized AsyncWaitSet, and provide convenient methods to register
    // callbacks for DDS events (data_available, subscription_matched, liveliness_changed, etc.)

    // Setup Reader Interfaces
    auto command_reader = std::make_shared<DDSReaderSetup<example_types::Command>>(
        participant_setup,
        topics::COMMAND_TOPIC,
        qos_profiles::ASSIGNER);

    auto button_reader = std::make_shared<DDSReaderSetup<example_types::Button>>(
        participant_setup,
        topics::BUTTON_TOPIC,
        qos_profiles::ASSIGNER);

    auto config_reader = std::make_shared<DDSReaderSetup<example_types::Config>>(
        participant_setup,
        topics::CONFIG_TOPIC,
        qos_profiles::ASSIGNER);

    // Setup Writer Interfaces
    auto position_writer = std::make_shared<DDSWriterSetup<example_types::Position>>(
        participant_setup,
        topics::POSITION_TOPIC,
        qos_profiles::ASSIGNER);

    // Enable Asynchronous Event-Driven processing for readers
    command_reader->set_data_available_handler(process_command_data);
    command_reader->set_liveliness_changed_handler(on_command_liveliness_changed);
    button_reader->set_data_available_handler(process_button_data);
    config_reader->set_data_available_handler(process_config_data);

    // Set publication matched callback for writer
    position_writer->set_publication_matched_handler(on_position_publication_matched);

    rti::config::Logger::instance().notice("Example I/O app is running. Press Ctrl+C to stop.");
    rti::config::Logger::instance().notice("Subscribing to Command, Button, and Config messages...");
    rti::config::Logger::instance().notice("Publishing Position messages...");


    example_types::Position pos_msg;
    pos_msg.source_id(APP_NAME);

    // Counter for tracking iterations
    int iteration = 0;

    while (!application::shutdown_requested) {

      try
      {
        // Populate and send position message
        pos_msg.latitude(37.7749);
        pos_msg.longitude(-122.4194);
        pos_msg.altitude(15.0);
        pos_msg.timestamp_sec(static_cast<int32_t>(std::time(nullptr)));
        position_writer->writer().write(pos_msg);

        // Log every position publish at DEBUG level (can be filtered)
        rti::config::Logger::instance().debug(("[POSITION] Published ID: " + std::string(pos_msg.source_id()) +
                    ", Lat: " + std::to_string(pos_msg.latitude()) +
                    ", Lon: " + std::to_string(pos_msg.longitude()) +
                    ", Alt: " + std::to_string(pos_msg.altitude()) + "m" +
                    ", Timestamp: " + std::to_string(pos_msg.timestamp_sec())).c_str());
        
        // Every 10 iterations (5 seconds), log INFORMATIONAL level status to distributed logger
        if (iteration % 10 == 0) {
          rti::config::Logger::instance().informational(("Application running - Position published at " + 
                      std::to_string(pos_msg.timestamp_sec())).c_str());
        }
        
        iteration++;
      }
      catch (const std::exception &ex)
      {
        rti::config::Logger::instance().error(("Failed to publish position: " + std::string(ex.what())).c_str());
      }

      // Alternate Option: Use Polling Method to Read Data
      // Latency contingent on loop rate
      // process_command_data(command_reader->reader());

      // Sleep
      std::this_thread::sleep_for(std::chrono::milliseconds(500));

    }

    rti::config::Logger::instance().informational("Example I/O application shutting down...");
    rti::config::Logger::instance().notice("Example I/O application stopped");
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
            qos_profiles::DEFAULT_PARTICIPANT,
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
        } catch (const std::exception& ex) {
            std::cerr << "Error initializing DistLogger: " << ex.what() << std::endl;
            throw;
        }
        
        // Run the application
        run(participant_setup);
        
    } catch (const std::exception& ex) {
        // This will catch DDS exceptions
        std::cerr << "Exception in main: " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

    // Finalize Distributed Logger before participant factory
    try {
        rti::dist_logger::DistLogger::finalize();
        std::cout << "DistLogger finalized at application exit" << std::endl;
    } catch (const std::exception &e) {
        std::cerr << "Error finalizing DistLogger at exit: " << e.what() << std::endl;
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