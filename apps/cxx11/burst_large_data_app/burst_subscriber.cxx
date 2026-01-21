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
const int LOG_FREQUENCY = 100;
const int MAIN_LOOP_SLEEP_MS = 500;

void process_data(
        dds::sub::DataReader<example_types::FinalFlatPointCloud> &reader)
{
    static unsigned long samples_received = 0;
    try {
        auto samples = reader.take();
        for (const auto &sample : samples) {
            // Check if message is not DDS metadata
            if (sample.info().valid()) {
                samples_received++;
                if (samples_received % LOG_FREQUENCY == 0) {
                    // NOTE: Using std::cout here for example clarity only. In
                    // production, rti_logger.informational() is recommended for
                    // distributed logging.
                    std::cout << "Samples received: " << samples_received
                              << ", size: "
                              << sample.data().root().data().element_count()
                              << " B" << std::endl;
                }
            }
        }
    } catch (const std::exception &ex) {
        rti::config::Logger::instance().error(
                (std::string("Failed to process data: ")
                 + std::string(ex.what()))
                        .c_str());
    }
}

void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    auto &rti_logger = rti::config::Logger::instance();

    rti_logger.notice(
            (std::string("Burst subscriber application starting on domain ")
             + std::to_string(participant_setup->participant().domain_id()))
                    .c_str());

    // Setup Reader Interface for FlatData type
    auto burst_reader = std::make_shared<
            DDSReaderSetup<example_types::FinalFlatPointCloud>>(
            participant_setup,
            topics::POINT_CLOUD_TOPIC,
            qos_profiles::BURST_LARGE_DATA_UDP);

    // Enable Asynchronous Event-Driven processing for reader
    burst_reader->set_data_available_handler(process_data);

    // Attach a handler for Sample Lost DDS event
    burst_reader->set_sample_lost_handler(
            [](dds::sub::DataReader<example_types::FinalFlatPointCloud>
                       &reader) {
                auto status = reader.sample_lost_status();
                // NOTE: Using std::cout here for example clarity only. In
                // production, rti_logger.warning() is recommended for
                // distributed logging.
                std::cout << "Sample lost! Total lost: " << status.total_count()
                          << std::endl;
            });

    rti_logger.informational(
            "Burst subscriber app is running. Press Ctrl+C to stop.");

    while (!application::shutdown_requested) {
        // Sleep
        std::this_thread::sleep_for(
                std::chrono::milliseconds(MAIN_LOOP_SLEEP_MS));
    }

    rti_logger.informational("Burst subscriber application shutting down...");
}

int main(int argc, char *argv[])
{
    using namespace application;

    // Parse arguments and handle control-C
    auto arguments =
            parse_arguments(argc, argv, "Burst subscriber application.");
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
                qos_profiles::LARGE_DATA_UDP_PARTICIPANT,
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