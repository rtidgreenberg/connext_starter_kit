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

// For example legibility.
using namespace rti::all;
using namespace rti::dist_logger;

constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;
const std::string APP_NAME = "Burst Subscriber app";
unsigned long samples_received = 0;

void process_data(dds::sub::DataReader<example_types::FinalFlatPointCloud> reader)
{
    auto samples = reader.take();
    for (const auto& sample : samples)
    {
      // Check if message is not DDS metadata
      if (sample.info().valid()) {
            samples_received ++;
            if (samples_received % 100 == 0) {
                rti::config::Logger::instance().informational((std::string("Samples received: ") + std::to_string(samples_received) +
                        ", size: " + std::to_string(sample.data().root().data().element_count()) + " B").c_str());
            }
      }
    }
} 

void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    auto& rti_logger = rti::config::Logger::instance();
    
    rti_logger.notice((std::string("Burst subscriber application starting on domain ") + std::to_string(participant_setup->participant().domain_id())).c_str());

    // Setup Reader Interface for FlatData type
    auto burst_reader = std::make_shared<DDSReaderSetup<example_types::FinalFlatPointCloud>>(
        participant_setup,
        topics::POINT_CLOUD_TOPIC,
        qos_profiles::BURST_LARGE_DATA_UDP);

    // Enable Asynchronous Event-Driven processing for reader
    burst_reader->set_data_available_handler(process_data);
    burst_reader->set_sample_lost_handler(
        [](dds::sub::DataReader<example_types::FinalFlatPointCloud>& reader)
        {
            auto status = reader.sample_lost_status();
            rti::config::Logger::instance().warning(
                    (std::string("Sample lost! Total lost: ")
                     + std::to_string(status.total_count()))
                            .c_str());
        });

    rti_logger.informational("Burst subscriber app is running. Press Ctrl+C to stop.");

    while (!application::shutdown_requested) {

      // Alternate Option: Use Polling Method to Read Data
      // Latency contingent on loop rate
      // process_data(burst_reader->reader());

      // Sleep
      std::this_thread::sleep_for(std::chrono::milliseconds(500));

    }

    rti_logger.informational("Burst subscriber application shutting down...");
}

int main(int argc, char *argv[])
{
    using namespace application;

    // Parse arguments and handle control-C
    auto arguments = parse_arguments(argc, argv, "Burst subscriber application.");
    if (arguments.parse_result == ParseReturn::exit) {
        return EXIT_SUCCESS;
    } else if (arguments.parse_result == ParseReturn::failure) {
        return EXIT_FAILURE;
    }
    setup_signal_handlers();

    // Run the application
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
            qos_profiles::LARGE_DATA_UDP_PARTICIPANT,
            APP_NAME);
        
        // Setup DistLogger Singleton
        // DistLogger provides distributed logging over DDS network. By using the shared participant,
        // all RTI Logger messages are published to remote subscribers via DDS topics, enabling centralized
        // logging and monitoring across distributed systems. This is more powerful than console logging.
        DistLoggerOptions options;
        options.domain_participant(participant_setup->participant());
        options.application_kind(APP_NAME);

        // Disable Logger output to console
        options.echo_to_stdout(true);
        
        DistLogger::set_options(options);
        auto& dist_logger = DistLogger::get_instance();
        
        // Configure DistLogger Verbosity. 
        // Passthrough for rti::config::logger verbosity control
        // Change Category to display internal Connext debug logs
        dist_logger.set_verbosity(rti::config::LogCategory::user, arguments.verbosity);
        
        // Configure Filter Level. This controls what level gets published
        dist_logger.set_filter_level(dist_logger.get_info_log_level());
        
        rti::config::Logger::instance().notice("DistLogger initialized with shared participant");
        rti::config::Logger::instance().notice(("Using QoS file: " + arguments.qos_file_path).c_str());
        
        run(participant_setup);
        
        // Explicitly finalize DistLogger Singleton before Domain Participant 
        // destruction as it uses it
        DistLogger::get_instance().finalize();
        std::cout << "DistLogger finalized" << std::endl;
        
    } catch (const std::exception& ex) {
        std::cerr << "Exception: " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

    // Finalize participant factory after all DDSParticipantSetup/DDSReaderSetup/DDSWriterSetup objects are destroyed
    // This should be called at application exit after all DDS entities are cleaned up
    dds::domain::DomainParticipant::finalize_participant_factory();
    std::cout << "DomainParticipant factory finalized at application exit" << std::endl;

    return EXIT_SUCCESS;
}