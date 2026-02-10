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
const std::string APP_NAME = "Example CXX IO FOXGLOVE";


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

void on_position_publication_matched(dds::pub::DataWriter<::foxglove::GeoJSON> writer)
{
    auto status = writer->publication_matched_status();
    rti::config::Logger::instance().notice(
        ("[POSITION] Publication matched - current_count: " +
         std::to_string(status.current_count()) + ", total_count: " +
         std::to_string(status.total_count())).c_str());
}


void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    auto& rti_logger = rti::config::Logger::instance();

    rti_logger.notice(("Example I/O application starting on domain " + std::to_string(participant_setup->participant().domain_id())).c_str());

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
    auto position_writer = std::make_shared<DDSWriterSetup<::foxglove::GeoJSON>>(
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

    rti_logger.notice("Example I/O app is running. Press Ctrl+C to stop.");
    rti_logger.notice("Subscribing to Command, Button, and Config messages...");
    rti_logger.notice("Publishing Position messages...");


    ::foxglove::GeoJSON pos_msg;

    // Counter for tracking iterations
    int iteration = 0;

    while (!application::shutdown_requested) {

      try
      {
        // Populate and send position message
        std::string json_string = R"({
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [-122.4194, 37.7749]
      },
      "properties": {
        "name": "Alhambra"
      }
    }
  ]
})";        
        pos_msg.geojson(json_string);
        position_writer->writer().write(pos_msg);

        // Log every position publish
        std::cout << "[POSITION]" << std::endl;
        
        // Every 10 iterations (5 seconds), log status to distributed logger
        if (iteration % 10 == 0) {
          rti_logger.informational(("Application running "));
        }
        
        iteration++;
      }
      catch (const std::exception &ex)
      {
        rti_logger.error(("Failed to publish position: " + std::string(ex.what())).c_str());
      }

      // Alternate Option: Use Polling Method to Read Data
      // Latency contingent on loop rate
      // process_command_data(command_reader->reader());

      // Sleep
      std::this_thread::sleep_for(std::chrono::milliseconds(500));

    }

    rti_logger.informational("Example I/O application shutting down...");
    rti_logger.notice("Example I/O application stopped");
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
        // DDS Participant Setup (creates DomainParticipant and AsyncWaitSet)
        // DDSParticipantSetup is an example wrapper class for your convenience 
        // 1. Creates the participant in the specified domain
        // 2. Sets up the AsyncWaitSet with a configurable thread pool 
        // 3. Loads QoS profiles from the XML file and stores for readers/writers
        auto participant_setup = std::make_shared<DDSParticipantSetup>(
            arguments.domain_id,
            ASYNC_WAITSET_THREADPOOL_SIZE,
            arguments.qos_file_path,
            qos_profiles::DEFAULT_PARTICIPANT,
            APP_NAME);

        // Setup Distributed Logger Singleton
        // This publishes the RTI logs over DDS the network, enabling
        // centralized logging and monitoring across distributed systems. 
        // By re-using the application Domain Participant, we optimize the resource usage.

        DistLoggerOptions options;
        options.domain_participant(participant_setup->participant());
        options.application_kind(APP_NAME);       
        DistLogger::set_options(options);
        auto& dist_logger = DistLogger::get_instance();
        
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
        dist_logger.set_verbosity(rti::config::LogCategory::user, arguments.verbosity);
        
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
        
    } catch (const std::exception& ex) {
        std::cerr << "Exception: " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

    // Finalize participant factory after all DDS entities are cleaned up
    dds::domain::DomainParticipant::finalize_participant_factory();
    std::cout << "DomainParticipant factory finalized at application exit" << std::endl;

    return EXIT_SUCCESS;
}