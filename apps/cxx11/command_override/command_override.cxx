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


void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    rti::config::Logger::instance().notice("Command Override application starting...");

    // DDSReaderSetup and DDSWriterSetup are example wrapper classes for your convenience that simplify
    // DDS reader/writer creation and event handling. They manage DataReader/DataWriter lifecycle, attach
    // status conditions to the centralized AsyncWaitSet, and provide convenient methods to register
    // callbacks for DDS events (data_available, subscription_matched, liveliness_changed, etc.)

    // Setup Reader Interface (Command subscriber)
    auto command_reader =
            std::make_shared<DDSReaderSetup<example_types::Command>>(
                    participant_setup,
                    topics::COMMAND_TOPIC,
                    qos_profiles::COMMAND_STRENGTH_10);

    // Set a custom handler for subscription matched events (optional)
    // If not set, default handler will be used
    command_reader->set_subscription_matched_handler(process_subscription_matched);

    // Setup Writer Interfaces (3 Command publishers)
    auto command_writer_10 =
            std::make_shared<DDSWriterSetup<example_types::Command>>(
                    participant_setup,
                    topics::COMMAND_TOPIC,
                    qos_profiles::COMMAND_STRENGTH_10);

    auto command_writer_20 =
            std::make_shared<DDSWriterSetup<example_types::Command>>(
                    participant_setup,
                    topics::COMMAND_TOPIC,
                    qos_profiles::COMMAND_STRENGTH_20);

    auto command_writer_30 =
            std::make_shared<DDSWriterSetup<example_types::Command>>(
                    participant_setup,
                    topics::COMMAND_TOPIC,
                    qos_profiles::COMMAND_STRENGTH_30);

    // Enable Asynchronous Event-Driven processing for command reader
    command_reader->set_data_available_handler(process_command_data);

    rti::config::Logger::instance().notice("Command Override app is running. Press Ctrl+C to stop.");
    rti::config::Logger::instance().notice("Subscribing to Command messages...");
    rti::config::Logger::instance().notice("Publishing Command messages...");

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
            rti::config::Logger::instance().error(
                    ("Failed to publish commands: " + std::string(ex.what())).c_str());
        }

        // Sleep for 1 second (1 Hz)
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    }

    rti::config::Logger::instance().notice("Command Override application shutting down...");

    rti::config::Logger::instance().notice("Command Override application stopped");
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
    } catch (const std::exception &ex) {
        // This will catch DDS exceptions
        std::cerr << "Exception in run(): " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

    // Finalize participant factory after all DDSParticipantSetup/DDSReaderSetup/DDSWriterSetup objects
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