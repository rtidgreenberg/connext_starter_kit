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

// include both the standard APIs and extensions
#include <rti/rti.hpp>
#include <rti/core/cond/AsyncWaitSet.hpp>

//
// For more information about the headers and namespaces, see:
//    https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/api/connext_dds/api_cpp2/group__DDSNamespaceModule.html
// For information on how to use extensions, see:
//    https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/api/connext_dds/api_cpp2/group__DDSCpp2Conventions.html

#include "application.hpp"  // for command line parsing and ctrl-c
#include "ExampleTypes.hpp"
#include "DDSDefs.hpp"
#include "DDSContextSetup.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"

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

        // Do something with data message
        std::cout << sample.data() << std::endl;

        // overloaded -> operator to use RTI extension
        std::cout << reader->topic_name() << " received" << std::endl;
      }
    }
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
        std::cout << sample.data() << std::endl;

        // overloaded -> operator to use RTI extension
        std::cout << reader->topic_name() << " received" << std::endl;
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
        std::cout << sample.data() << std::endl;

        // overloaded -> operator to use RTI extension
        std::cout << reader->topic_name() << " received" << std::endl;
      }
    }
} 


void run(unsigned int domain_id, const std::string& qos_file_path)
{
    // Use provided QoS file path and generated constants from IDL
    const std::string qos_profile = dds_config::DEFAULT_PARTICIPANT_QOS;

    std::cout << "Example I/O application starting on domain " << domain_id << std::endl;
    std::cout << "Using QoS file: " << qos_file_path << std::endl;

    // This sets up DDS Domain Participant as well as the Async Waitset for the readers
  auto dds_context = std::make_shared<DDSContextSetup>(domain_id, ASYNC_WAITSET_THREADPOOL_SIZE, qos_file_path, qos_profile, APP_NAME);
    
    // Get reference to distributed logger
    auto& logger = dds_context->distributed_logger();

    // Setup Reader Interfaces
    auto command_reader = std::make_shared<DDSReaderSetup<example_types::Command>>(
        dds_context,
        topics::COMMAND_TOPIC,
        qos_file_path,
        dds_config::ASSIGNER_QOS);

    auto button_reader = std::make_shared<DDSReaderSetup<example_types::Button>>(
        dds_context,
        topics::BUTTON_TOPIC,
        qos_file_path,
        dds_config::ASSIGNER_QOS);

    auto config_reader = std::make_shared<DDSReaderSetup<example_types::Config>>(
        dds_context,
        topics::CONFIG_TOPIC,
        qos_file_path,
        dds_config::ASSIGNER_QOS);

    // Setup Writer Interfaces
    auto position_writer = std::make_shared<DDSWriterSetup<example_types::Position>>(
        dds_context,
        topics::POSITION_TOPIC,
        qos_file_path,
        dds_config::ASSIGNER_QOS);

    // Enable Asynchronous Event-Driven processing for readers
    command_reader->set_data_available_handler(process_command_data);
    button_reader->set_data_available_handler(process_button_data);
    config_reader->set_data_available_handler(process_config_data);

    logger.info("Example I/O app is running. Press Ctrl+C to stop.");
    logger.info("Subscribing to Command, Button, and Config messages...");
    logger.info("Publishing Position messages...");


    example_types::Position pos_msg;
    pos_msg.source_id(APP_NAME);

    while (!application::shutdown_requested) {

      try
      {
        // Populate and send position message
        pos_msg.latitude(37.7749);
        pos_msg.longitude(-122.4194);
        pos_msg.altitude(15.0);
        position_writer->writer().write(pos_msg);

        std::cout << "[POSITION] Published ID: " << pos_msg.source_id()
                  << ", Lat: " << pos_msg.latitude()
                  << ", Lon: " << pos_msg.longitude()
                  << ", Alt: " << pos_msg.altitude() << "m" << std::endl;
      }
      catch (const std::exception &ex)
      {
        logger.error("Failed to publish position: " + std::string(ex.what()));
      }

      // Alternate Option: Use Polling Method to Read Data
      // Latency contingent on loop rate
      // process_command_data(command_reader->reader());

      // Sleep
      std::this_thread::sleep_for(std::chrono::seconds(1));

    }

    logger.info("Example I/O application shutting down...");
    
    logger.info("Example I/O application stopped");
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
        run(arguments.domain_id, arguments.qos_file_path);
    } catch (const std::exception& ex) {
        // This will catch DDS exceptions
        std::cerr << "Exception in run(): " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

  // Finalize participant factory after all DDSContextSetup/DDSReaderSetup/DDSWriterSetup objects are destroyed
  // This should be called at application exit after all DDS entities are cleaned up
    try
    {
        dds::domain::DomainParticipant::finalize_participant_factory();
        std::cout << "DomainParticipant factory finalized at application exit" << std::endl;
    }
    catch (const std::exception &e)
    {
        std::cerr << "Error finalizing participant factory at exit: " << e.what() << std::endl;
    }

    return EXIT_SUCCESS;
}