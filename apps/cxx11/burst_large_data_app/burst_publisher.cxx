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
#include "DDSWriterSetup.hpp"

// For example legibility.
using namespace rti::all;
using namespace rti::dist_logger;

constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;
const std::string APP_NAME = "Burst Publisher app";
const int LOG_FREQUENCY = 100;
const int ACKNOWLEDGMENT_TIMEOUT_MS = 5000;
const int MICROSECONDS_PER_SECOND = 1000000;

void burst_duration_statistics(
        const std::chrono::high_resolution_clock::time_point &start_time,
        unsigned long samples_sent)
{
    auto end_time = std::chrono::high_resolution_clock::now();
    auto duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                               end_time - start_time)
                               .count();
    auto duration_secs = duration_ms / 1000.0;
    auto avg_time_per_point_cloud = duration_ms / (samples_sent);
    auto effective_rate = (samples_sent) / duration_secs;

    std::cout << "Burst statistics:" << std::endl;
    std::cout << "  Samples sent: " << samples_sent << std::endl;
    std::cout << "  Total duration: " << duration_ms << " ms (" << duration_secs
              << " seconds)" << std::endl;
    std::cout << "  Average time per point cloud: " << avg_time_per_point_cloud
              << " ms" << std::endl;
    std::cout << "  Actual send rate: " << effective_rate << " Hz\n"
              << std::endl;
}

void sleep_until_next_sample(
        std::chrono::high_resolution_clock::time_point &next_target_time,
        const std::chrono::microseconds &sample_interval_us)
{
    auto now = std::chrono::high_resolution_clock::now();
    next_target_time = next_target_time + sample_interval_us;
    if (next_target_time > now) {
        std::this_thread::sleep_until(next_target_time);
    }
}

void run(
        std::shared_ptr<DDSParticipantSetup> participant_setup,
        unsigned int send_rate,
        unsigned int burst_duration)
{
    auto &rti_logger = rti::config::Logger::instance();

    rti_logger.notice(
            ("Burst publisher application starting on domain "
             + std::to_string(participant_setup->participant().domain_id()))
                    .c_str());

    // Setup Writer Interface for type
    auto burst_writer = std::make_shared<
            DDSWriterSetup<example_types::FinalFlatPointCloud>>(
            participant_setup,
            topics::POINT_CLOUD_TOPIC,
            qos_profiles::BURST_LARGE_DATA_UDP);

    rti_logger.informational(
            "Burst publisher app is running. Press Ctrl+C to stop.");

    // For demonstration purposes, we want to wait for at 
    // least 1 DataReader to match
    auto expected_drs = 1;
    burst_writer->wait_for_drs_to_match(expected_drs);

    unsigned long samples_to_send = burst_duration * send_rate;

    const uint32_t POINT_CLOUD_SIZE = example_types::MAX_POINT_CLOUD_SIZE;
    unsigned long point_cloud_counter = 0;
    auto writer = burst_writer->writer();

    // NOTE: Using std::cout here for example clarity only. In production,
    // rti_logger.informational() is recommended for distributed logging.
    std::cout << "Starting burst of " << samples_to_send << " point clouds ("
              << POINT_CLOUD_SIZE << " B) at " << send_rate
              << " Hz. Bandwidth: "
              << (send_rate * POINT_CLOUD_SIZE * 8 / 1000000) << " Mbps"
              << std::endl;

    // Let's measure how long it takes to send these samples
    auto burst_start_time = std::chrono::high_resolution_clock::now();

    // Calculate the interval between samples in microseconds with high
    // precision (MICROSECONDS_PER_SECOND microseconds = 1 second)
    auto sample_interval_us =
            std::chrono::microseconds(MICROSECONDS_PER_SECOND / send_rate);
    auto next_target_time = burst_start_time + sample_interval_us;

    while (!application::shutdown_requested
           && point_cloud_counter < samples_to_send) {
        try {
            point_cloud_counter++;
            auto sample = writer->get_loan();
            auto root = sample->root();

            // Set fields directly on the loaned sample
            root.point_cloud_id(point_cloud_counter);

            // Write the loaned sample. This transfers ownership
            writer.write(*sample);
            if (point_cloud_counter % LOG_FREQUENCY == 0) {
                rti_logger.informational(
                        ("Published ID: " + std::to_string(point_cloud_counter)
                         + " point clouds")
                                .c_str());
            }
        } catch (const std::exception &ex) {
            rti_logger.error(("Failed to publish point cloud "
                              + std::to_string(point_cloud_counter) + ": "
                              + ex.what())
                                     .c_str());
        }

        // Sleep until next sample needs to be sent
        if (point_cloud_counter < samples_to_send) {
            sleep_until_next_sample(next_target_time, sample_interval_us);
        }
    }

    // Wait for all samples to be acknowledged by the DataReader
    writer.wait_for_acknowledgments(
            dds::core::Duration::from_millisecs(ACKNOWLEDGMENT_TIMEOUT_MS));
    rti_logger.informational(
            "DataReader has confirmed that it has received all the samples.");

    // Calculate how long it took to send the burst and print it
    burst_duration_statistics(burst_start_time, point_cloud_counter);

    rti_logger.informational("Burst publisher application shutting down...");
}

int main(int argc, char *argv[])
{
    using namespace application;

    // Parse arguments and handle control-C
    auto arguments =
            parse_arguments(argc, argv, "Burst publisher application.");
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
        // 3. Loads QoS profiles from the XML file and stores for
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
        run(participant_setup, arguments.send_rate, arguments.burst_duration);

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