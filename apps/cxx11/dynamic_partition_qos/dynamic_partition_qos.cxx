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
#include <ctime>
#include <sstream>
#include <iomanip>
#include <random>

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
#include "Definitions.hpp"
#include "DDSContextSetup.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"

constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;
constexpr int PUBLISH_PERIOD_MS = 2000;
const std::string APP_NAME = "Dynamic Partition QoS App";


void process_command_data(dds::sub::DataReader<example_types::Command> reader)
{
    auto samples = reader.take();
    
    for (const auto& sample : samples)
    {
      // Check if message is not DDS metadata
      if (sample.info().valid())
      {

        // overloaded -> operator to use RTI extension
        std::cout << "\n\nMESSAGE RECEIVED: " << sample.data().message() << "\n" << std::endl;
      }
    }
} 


void run(unsigned int domain_id, const std::string& qos_file_path)
{
    // Generate random Application ID
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> distrib(1000, 9999);
    int app_id = distrib(gen);
    
    // Create application name with App ID
    std::stringstream app_name_stream;
    app_name_stream << APP_NAME << " [App-" << app_id << "]";
    std::string app_name_with_id = app_name_stream.str();
    
    // Use provided QoS file path and generated constants from IDL
    const std::string qos_profile = qos_profiles::DEFAULT_PARTICIPANT;

    std::cout << "Dynamic Partition QoS application starting on domain " << domain_id << std::endl;
    std::cout << "Application ID: " << app_id << std::endl;
    std::cout << "Using QoS file: " << qos_file_path << std::endl;

    // This sets up DDS Domain Participant as well as the Async Waitset for the readers
    auto dds_context = std::make_shared<DDSContextSetup>(domain_id, ASYNC_WAITSET_THREADPOOL_SIZE, qos_file_path, qos_profile, app_name_with_id);
    
    // Get reference to distributed logger
    auto& logger = dds_context->distributed_logger();

    // Setup Writer Interface
    auto command_writer = std::make_shared<DDSWriterSetup<example_types::Command>>(
        dds_context,
        topics::COMMAND_TOPIC,
        qos_file_path,
        qos_profiles::ASSIGNER);

    // Setup Reader Interface
    auto command_reader = std::make_shared<DDSReaderSetup<example_types::Command>>(
        dds_context,
        topics::COMMAND_TOPIC,
        qos_file_path,
        qos_profiles::ASSIGNER);

    // Configure reader to ignore own publications
    // Get the DataWriter's instance handle and tell the reader to ignore it
    dds::core::InstanceHandle writer_handle = command_writer->writer()->instance_handle();
    dds::sub::ignore(dds_context->participant(), writer_handle);

    // Enable Asynchronous Event-Driven processing for reader
    command_reader->set_data_available_handler(process_command_data);

    logger.info("Dynamic Partition QoS app is running. Press Ctrl+C to stop.");
    logger.info("Subscribing to Command messages...");
    logger.info("Publishing Command messages...");
    logger.info("Type a partition name at any time to change participant partition QoS (e.g., 'MyPartition' or 'Partition1,Partition2')");

    // Start input thread for partition changes
    std::thread input_thread([&logger, &dds_context, app_id]() {
        std::string input;
        while (!application::shutdown_requested) {
            std::getline(std::cin, input);
            
            if (input.empty()) {
                continue;
            }
            
            if (input == "q" || input == "exit") {
                application::shutdown_requested = true;
                break;
            }
            
            // Parse partition string(s) - split by comma
            std::vector<std::string> partitions;
            std::stringstream ss(input);
            std::string partition;
            
            while (std::getline(ss, partition, ',')) {
                // Trim whitespace
                size_t start = partition.find_first_not_of(" \t");
                size_t end = partition.find_last_not_of(" \t");
                if (start != std::string::npos && end != std::string::npos) {
                    partitions.push_back(partition.substr(start, end - start + 1));
                }
            }
            
            if (partitions.empty()) {
                std::cerr << "Error: No valid partition names provided" << std::endl;
                continue;
            }
            
            // Apply partition QoS to domain participant
            try {
                std::cout << "Applying partition(s): ";
                for (size_t i = 0; i < partitions.size(); ++i) {
                    std::cout << "'" << partitions[i] << "'";
                    if (i < partitions.size() - 1) std::cout << ", ";
                }
                std::cout << std::endl;
                
                logger.info("User requested partition change to: " + input);
                
                // Get current participant QoS
                auto participant_qos = dds_context->participant().qos();
                
                // Update partition policy
                participant_qos << dds::core::policy::Partition(partitions);
                
                // Apply the new QoS to the participant
                dds_context->participant().qos(participant_qos);
                
                std::cout << "Partition QoS applied successfully!" << std::endl;
                logger.info("Partition QoS updated successfully");
                
            } catch (const dds::core::Error& ex) {
                std::cerr << "Error applying partition QoS: " << ex.what() << std::endl;
                logger.error("Failed to apply partition QoS: " + std::string(ex.what()));
            }
        }
    });

    // Create Command Message
    example_types::Command cmd_msg;
    cmd_msg.destination_id("system");
    cmd_msg.command_type(example_types::CommandType::COMMAND_START);
    cmd_msg.urgent(false);
    
    // Add App ID to message
    std::stringstream msg_stream;
    msg_stream << "From APP ID: " << app_id;
    cmd_msg.message(msg_stream.str());

    int count = 0;
    while (!application::shutdown_requested) {

      try
      {
        // Get and display current partition(s) with App ID
        auto current_qos = dds_context->participant().qos();
        auto partitions = current_qos.policy<dds::core::policy::Partition>().name();


        std::cout << "\n------------------ APP ID:" << app_id << " PARTITION: ";
        if (partitions.empty()) {
            std::cout << "(default/empty)";
        } else {
            for (size_t i = 0; i < partitions.size(); ++i) {
                std::cout << "'" << partitions[i] << "'";
                if (i < partitions.size() - 1) std::cout << ", ";
            }
        }
        std::cout << "-----------------------"  << std::endl;
        std::cout << "\nEnter partition name(s) (comma-separated for multiple, "
                     "or 'q'/'exit' to quit): " << std::endl;


        // Send Message
        command_writer->writer().write(cmd_msg);

        count++;
      }
      catch (const std::exception &ex)
      {
        logger.error("Failed to publish command: " + std::string(ex.what()));
      }

      // Sleep
      std::this_thread::sleep_for(std::chrono::milliseconds(PUBLISH_PERIOD_MS));

    }

    // Wait for input thread to finish
    if (input_thread.joinable()) {
        input_thread.join();
    }

    logger.info("Dynamic Partition QoS application shutting down...");
    
    logger.info("Dynamic Partition QoS application stopped");
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
