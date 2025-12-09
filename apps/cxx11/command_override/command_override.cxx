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
#include "Definitions.hpp"
#include "DDSContextSetup.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"

constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;
const std::string APP_NAME = "Command Override CXX APP";

// Enum for command publishing phases
enum class PublishingPhase {
    WRITER1_ONLY = 0,       // Phase 1: Writer 1 only
    WRITERS_1_AND_2 = 1,    // Phase 2: Writers 1 & 2 together
    ALL_WRITERS = 2,        // Phase 3: Writers 1, 2 & 3 together
    WRITER1_STRENGTH50 = 3  // Phase 4: Writer 1 with strength 50
};


// Helper function to convert CommandType enum to string
std::string command_type_to_string(example_types::CommandType cmd_type)
{
    switch (cmd_type) {
    case example_types::CommandType::COMMAND_START:
        return "START";
    case example_types::CommandType::COMMAND_STOP:
        return "STOP";
    case example_types::CommandType::COMMAND_PAUSE:
        return "PAUSE";
    case example_types::CommandType::COMMAND_RESET:
        return "RESET";
    case example_types::CommandType::COMMAND_SHUTDOWN:
        return "SHUTDOWN";
    default:
        return "UNKNOWN";
    }
}

void process_command_data(dds::sub::DataReader<example_types::Command> reader)
{
    auto samples = reader.take();
    for (const auto &sample : samples) {
        // Check if message is not DDS metadata
        if (sample.info().valid()) {
            std::cout << "------------------------------------\n"
                      << " Command received from: "
                      << sample.data().command_id() << " | Type: "
                      << command_type_to_string(sample.data().command_type())
                      << std::endl
                      << "------------------------------------" << std::endl;
        }
    }
}

void process_subscription_matched(dds::sub::DataReader<example_types::Command>& reader)
{
    auto status = reader.subscription_matched_status();
    std::cout << "*** Custom Callback *** Subscription matched for topic: " 
              << reader.topic_description().name() 
              << " | Publishers: " << status.current_count() << std::endl;
}


void run(unsigned int domain_id, const std::string &qos_file_path)
{
    // Use provided QoS file path and generated constants from IDL
    const std::string qos_profile = qos_profiles::DEFAULT_PARTICIPANT;

    std::cout << "Command Override application starting on domain " << domain_id
              << std::endl;
    std::cout << "Using QoS file: " << qos_file_path << std::endl;

    // This sets up DDS Domain Participant as well as the Async Waitset for the
    // readers
    auto dds_context = std::make_shared<DDSContextSetup>(
            domain_id,
            ASYNC_WAITSET_THREADPOOL_SIZE,
            qos_file_path,
            qos_profile,
            APP_NAME);

    // Get reference to distributed logger
    auto &logger = dds_context->distributed_logger();

    // Setup Reader Interface (Command subscriber)
    auto command_reader =
            std::make_shared<DDSReaderSetup<example_types::Command>>(
                    dds_context,
                    topics::COMMAND_TOPIC,
                    qos_file_path,
                    qos_profiles::COMMAND_STRENGTH_10);

    // Set a custom handler for subscription matched events (optional)
    // If not set, default handler will be used
    command_reader->set_subscription_matched_handler(process_subscription_matched);

    // Setup Writer Interfaces (3 Command publishers)
    auto command_writer_10 =
            std::make_shared<DDSWriterSetup<example_types::Command>>(
                    dds_context,
                    topics::COMMAND_TOPIC,
                    qos_file_path,
                    qos_profiles::COMMAND_STRENGTH_10);

    auto command_writer_20 =
            std::make_shared<DDSWriterSetup<example_types::Command>>(
                    dds_context,
                    topics::COMMAND_TOPIC,
                    qos_file_path,
                    qos_profiles::COMMAND_STRENGTH_20);

    auto command_writer_30 =
            std::make_shared<DDSWriterSetup<example_types::Command>>(
                    dds_context,
                    topics::COMMAND_TOPIC,
                    qos_file_path,
                    qos_profiles::COMMAND_STRENGTH_30);

    // Enable Asynchronous Event-Driven processing for command reader
    command_reader->set_data_available_handler(process_command_data);

    logger.info("Command Override app is running. Press Ctrl+C to stop.");
    logger.info("Subscribing to Command messages...");
    logger.info("Publishing Command messages...");

    // Create message instances with same command_id but different command types
    example_types::Command cmd_msg_1;
    cmd_msg_1.command_id("COMMAND_CTRL");
    cmd_msg_1.command_type(example_types::CommandType::COMMAND_START);

    example_types::Command cmd_msg_2;
    cmd_msg_2.command_id("COMMAND_CTRL");
    cmd_msg_2.command_type(example_types::CommandType::COMMAND_PAUSE);

    example_types::Command cmd_msg_3;
    cmd_msg_3.command_id("COMMAND_CTRL");
    cmd_msg_3.command_type(example_types::CommandType::COMMAND_RESET);

    PublishingPhase current_phase = PublishingPhase::WRITER1_ONLY;
    int phase_message_count = 0;
    const int MESSAGES_PER_PHASE = 10;

    while (!application::shutdown_requested) {
        try {
            // Progressive publishing pattern using switch statement
            switch (current_phase) {
            case PublishingPhase::WRITER1_ONLY:
                if (phase_message_count >= MESSAGES_PER_PHASE) {
                    current_phase = PublishingPhase::WRITERS_1_AND_2;
                    phase_message_count = 0;
                };

                // Phase 1: Writer 1 only
                command_writer_10->writer().write(cmd_msg_1);

                std::cout << "[PHASE 1 - COMMAND1]" << std::endl;


                break;

            case PublishingPhase::WRITERS_1_AND_2:
                if (phase_message_count >= MESSAGES_PER_PHASE) {
                    current_phase = PublishingPhase::ALL_WRITERS;
                    phase_message_count = 0;
                };

                // Phase 2: Writers 1 and 2 together
                command_writer_10->writer().write(cmd_msg_1);
                command_writer_20->writer().write(cmd_msg_2);

                std::cout << "[PHASE 2 - COMMAND1&2]" << std::endl;

                break;

            case PublishingPhase::ALL_WRITERS:
                if (phase_message_count >= MESSAGES_PER_PHASE) {
                    current_phase = PublishingPhase::WRITER1_STRENGTH50;
                    phase_message_count = 0;
                };

                // Phase 3: Writers 1, 2, and 3 all together
                command_writer_10->writer().write(cmd_msg_1);
                command_writer_20->writer().write(cmd_msg_2);
                command_writer_30->writer().write(cmd_msg_3);

                std::cout << "[PHASE 3 - COMMAND1&2&3]" << std::endl;


                break;

            case PublishingPhase::WRITER1_STRENGTH50:
                // Phase 4: Programmatically change writer 1's ownership
                // strength to 50
                if (phase_message_count == 1) {
                    // Only modify QoS once at the start of the phase

                    // Get QoS
                    auto qos_50 = command_writer_10->writer().qos();

                    // Change to 50
                    qos_50.policy<OwnershipStrength>().value(50);

                    // Set updated QoS
                    command_writer_10->writer().qos(qos_50);
                    std::cout << "!!! Writer 1 QoS changed to ownership "
                                 "strength 50 !!!"
                              << std::endl;
                }
                // ship it
                command_writer_10->writer().write(cmd_msg_1);
                command_writer_20->writer().write(cmd_msg_2);
                command_writer_30->writer().write(cmd_msg_3);

                std::cout << "[PHASE 4 - WRITER1_STRENGTH50]" << std::endl;

                if (phase_message_count >= MESSAGES_PER_PHASE) {
                    current_phase = PublishingPhase::WRITER1_ONLY;
                    phase_message_count = 0;
                };
                break;
            }

            // increment message count
            phase_message_count++;
            std::cout << "Message Count: " << phase_message_count << std::endl;
        } catch (const std::exception &ex) {
            logger.error(
                    "Failed to publish commands: " + std::string(ex.what()));
        }

        // Sleep for 1 second (1 Hz)
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    }

    logger.info("Command Override application shutting down...");

    logger.info("Command Override application stopped");
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
    } catch (const std::exception &ex) {
        // This will catch DDS exceptions
        std::cerr << "Exception in run(): " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

    // Finalize participant factory after all DDSContextSetup/DDSReaderSetup/DDSWriterSetup objects
    // are destroyed This should be called at application exit after all DDS
    // entities are cleaned up
    try {
        dds::domain::DomainParticipant::finalize_participant_factory();
        std::cout << "DomainParticipant factory finalized at application exit"
                  << std::endl;
    } catch (const std::exception &e) {
        std::cerr << "Error finalizing participant factory at exit: "
                  << e.what() << std::endl;
    }

    return EXIT_SUCCESS;
}