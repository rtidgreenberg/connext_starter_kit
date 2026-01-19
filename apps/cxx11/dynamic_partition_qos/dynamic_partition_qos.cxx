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


void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    // Generate random Application ID
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> distrib(1000, 9999);
    int app_id = distrib(gen);
    
    rti::config::Logger::instance().notice(("Dynamic Partition QoS application starting with App ID: " + std::to_string(app_id)).c_str());

    // DDSReaderSetup and DDSWriterSetup are example wrapper classes for your convenience that simplify
    // DDS reader/writer creation and event handling. They manage DataReader/DataWriter lifecycle, attach
    // status conditions to the centralized AsyncWaitSet, and provide convenient methods to register
    // callbacks for DDS events (data_available, subscription_matched, liveliness_changed, etc.)

    // Setup Writer Interface
    auto command_writer = std::make_shared<DDSWriterSetup<example_types::Command>>(
        participant_setup,
        topics::COMMAND_TOPIC,
        qos_profiles::ASSIGNER);

    // Setup Reader Interface
    auto command_reader = std::make_shared<DDSReaderSetup<example_types::Command>>(
        participant_setup,
        topics::COMMAND_TOPIC,
        qos_profiles::ASSIGNER);

    // Configure reader to ignore own publications
    // Get the DataWriter's instance handle and tell the reader to ignore it
    dds::core::InstanceHandle writer_handle = command_writer->writer()->instance_handle();
    dds::sub::ignore(participant_setup->participant(), writer_handle);

    // Enable Asynchronous Event-Driven processing for reader
    command_reader->set_data_available_handler(process_command_data);

    rti::config::Logger::instance().notice("Dynamic Partition QoS app is running. Press Ctrl+C to stop.");
    rti::config::Logger::instance().notice("Subscribing to Command messages...");
    rti::config::Logger::instance().notice("Publishing Command messages...");
    rti::config::Logger::instance().notice("Type a partition name at any time to change participant partition QoS (e.g., 'MyPartition' or 'Partition1,Partition2')");

    // Start input thread for partition changes
    std::thread input_thread([participant_setup, app_id]() {
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
                
                rti::config::Logger::instance().notice(("User requested partition change to: " + input).c_str());
                
                // Get current participant QoS
                auto participant_qos = participant_setup->participant().qos();
                
                // Update partition policy
                participant_qos << dds::core::policy::Partition(partitions);
                
                // Apply the new QoS to the participant
                participant_setup->participant().qos(participant_qos);
                
                std::cout << "Partition QoS applied successfully!" << std::endl;
                rti::config::Logger::instance().notice("Partition QoS updated successfully");
                
            } catch (const dds::core::Error& ex) {
                std::cerr << "Error applying partition QoS: " << ex.what() << std::endl;
                rti::config::Logger::instance().error(("Failed to apply partition QoS: " + std::string(ex.what())).c_str());
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
        auto current_qos = participant_setup->participant().qos();
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
        std::cerr << "Error: Failed to publish command: " << ex.what() << std::endl;
        rti::config::Logger::instance().error(("Failed to publish command: " + std::string(ex.what())).c_str());
      }

      // Sleep
      std::this_thread::sleep_for(std::chrono::milliseconds(PUBLISH_PERIOD_MS));

    }

    // Wait for input thread to finish
    if (input_thread.joinable()) {
        input_thread.join();
    }

    rti::config::Logger::instance().notice("Dynamic Partition QoS application shutting down...");
    
    rti::config::Logger::instance().notice("Dynamic Partition QoS application stopped");
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
