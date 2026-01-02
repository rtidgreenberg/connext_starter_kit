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
                std::cout << "Samples received: " << samples_received <<
                        ", size: " << sample.data().root().data().element_count() << " B" << std::endl;
            }
        // Process your data here
        // auto root = sample.data().root();
      }
    }
} 

void run(unsigned int domain_id, const std::string& qos_file_path)
{
    // Use provided QoS file path and generated constants from IDL
    // TODO: Make new assignment in XML file for ASSIGNER_QOS if needed
    const std::string qos_profile = std::string(qos_profiles::LARGE_DATA_UDP_PARTICIPANT);

    std::cout << "Burst subscriber application starting on domain " << domain_id << std::endl;
    std::cout << "Using QoS file: " << qos_file_path << std::endl;

    // This sets up DDS Domain Participant as well as the Async Waitset for the readers
    auto dds_context = std::make_shared<DDSContextSetup>(
            domain_id,
            ASYNC_WAITSET_THREADPOOL_SIZE,
            qos_file_path,
            qos_profile,
            APP_NAME);
    
    // Get reference to distributed logger
    auto& logger = dds_context->distributed_logger();

    // Setup Reader Interface for FlatData type
    auto burst_reader = std::make_shared<DDSReaderSetup<example_types::FinalFlatPointCloud>>(
        dds_context,
        topics::POINT_CLOUD_TOPIC,
        qos_file_path,
        qos_profiles::BURST_LARGE_DATA_UDP);

    // Enable Asynchronous Event-Driven processing for reader
    burst_reader->set_data_available_handler(process_data);
    burst_reader->set_sample_lost_handler(
        [&logger](dds::sub::DataReader<example_types::FinalFlatPointCloud>& reader)
        {
            auto status = reader.sample_lost_status();
            logger.warning("Sample lost! Total lost: " + std::to_string(status.total_count()));
        });

    logger.info("Burst subscriber app is running. Press Ctrl+C to stop.");

    while (!application::shutdown_requested) {

      // Alternate Option: Use Polling Method to Read Data
      // Latency contingent on loop rate
      // process_data(burst_reader->reader());

      // Sleep
      std::this_thread::sleep_for(std::chrono::milliseconds(500));

    }

    logger.info("Burst subscriber application shutting down...");
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