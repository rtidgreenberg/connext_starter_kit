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
#include <cstring>

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
const std::string APP_NAME = "FinalFlatImage CXX APP";


void process_final_flat_image_data(dds::sub::DataReader<example_types::FinalFlatImage> reader)
{
    auto samples = reader.take();
    for (const auto& sample : samples)
    {
      // Check if message is not DDS metadata
      if (sample.info().valid())
      {
        // Access FinalFlatImage sample root - FlatData types use .root()
        auto root = sample.data().root();
        
        std::cout << "[FINAL_FLAT_IMAGE] Received - ID: " << root.image_id()
                  << ", Width: " << root.width()
                  << ", Height: " << root.height()
                  << ", Format: " << root.format();
        
        // Access the fixed-size data array
        auto data_array = root.data();
        std::cout << ", Data array size: " << example_types::MAX_IMAGE_DATA_SIZE << " bytes (3 MB)" << std::endl;

        // overloaded -> operator to use RTI extension
        std::cout << reader->topic_name() << " received" << std::endl;
      }
    }
}

void run(unsigned int domain_id, const std::string& qos_file_path)
{
    // Use provided QoS file path and generated constants from IDL
    const std::string qos_profile = dds_config::LARGE_DATA_PARTICIPANT_QOS;

    std::cout << "FinalFlatImage application starting on domain " << domain_id << std::endl;
    std::cout << "Using QoS file: " << qos_file_path << std::endl;

    // This sets up DDS Domain Participant as well as the Async Waitset for the readers
  auto dds_context = std::make_shared<DDSContextSetup>(domain_id, ASYNC_WAITSET_THREADPOOL_SIZE, qos_file_path, qos_profile, APP_NAME);
    
    // Get reference to distributed logger
    auto& logger = dds_context->distributed_logger();

    // Setup Writer Interface for FinalFlatImage type
    auto final_flat_image_writer = std::make_shared<DDSWriterSetup<example_types::FinalFlatImage>>(
        dds_context,
        topics::FINAL_FLAT_IMAGE_TOPIC,
        qos_file_path,
        dds_config::LARGE_DATA_SHMEM_ZC_QOS);

    // Setup Reader Interface for FinalFlatImage type
    auto final_flat_image_reader = std::make_shared<DDSReaderSetup<example_types::FinalFlatImage>>(
        dds_context,
        topics::FINAL_FLAT_IMAGE_TOPIC,
        qos_file_path,
        dds_config::LARGE_DATA_SHMEM_ZC_QOS);

    // Enable Asynchronous Event-Driven processing for reader
    final_flat_image_reader->set_data_available_handler(process_final_flat_image_data);

    logger.info("FinalFlatImage app is running. Press Ctrl+C to stop.");
    logger.info("Publishing FinalFlatImage messages with @final @language_binding(FLAT_DATA) using zero-copy loan API...");

    int count = 0;

    while (!application::shutdown_requested) {

      try
      {
        // Zero-copy FlatData API for @final types using get_loan()
        auto writer = final_flat_image_writer->writer();
        
        // Get a loan from the writer - this provides zero-copy access to shared memory
        auto sample = writer->get_loan();
        
        // Access the root of the loaned sample
        auto root = sample->root();
        
        // Set fields directly on the loaned sample (zero-copy)
        root.image_id(count);
        root.width(640);
        root.height(480);
        root.format(0); // 0=RGB, 1=RGBA, 2=JPEG, etc.
        
        // Access and populate the fixed-size data array
        auto data_array = root.data();
        const int data_size = example_types::MAX_IMAGE_DATA_SIZE; // 3 MB payload
        for (int i = 0; i < data_size; i++) {
            data_array.set_element(i, static_cast<uint8_t>(i % 256));
        }

        // Write the loaned sample - this transfers ownership, don't discard after write
        writer.write(*sample);

        // Get DataWriter protocol status
        rti::core::status::DataWriterProtocolStatus status = writer->datawriter_protocol_status();

        auto first_unack_seq = status.first_unacknowledged_sample_sequence_number();
        auto first_available_seq =
                status.first_available_sample_sequence_number();
        auto last_available_seq =
                status.last_available_sample_sequence_number();

        auto send_window = status.send_window_size();

        std::cout << "First unacknowledged sample sequence number: " << first_unack_seq << std::endl;
        std::cout << "Send window size (max unacknowledged samples): " << send_window << std::endl;
        std::cout << "First available sample sequence number: "
                  << first_available_seq << std::endl;
        std::cout << "Last available sample sequence number: "
                  << last_available_seq << std::endl;


        std::cout << "[FINAL_FLAT_IMAGE] Published - ID: " << count
                  << ", Width: 640, Height: 480, Format: 0 (RGB), Data size: " 
                  << data_size << " bytes (3 MB payload)" << std::endl;

        count++;

        try {
            writer.wait_for_acknowledgments(dds::core::Duration(5, 0));
            std::cout << "All samples acknowledged by all reliable DataReaders."
                      << std::endl;
        } catch (const dds::core::TimeoutError &) {
            std::cout << "Timeout: Not all samples were acknowledged in time."
                      << std::endl;
        }
      }
      catch (const std::exception &ex)
      {
        logger.error("Failed to publish FinalFlatImage: " + std::string(ex.what()));
      }

      // Sleep for 100ms to achieve 10 Hz send rate
      std::this_thread::sleep_for(std::chrono::milliseconds(100));

    }

    logger.info("FinalFlatImage application shutting down...");
    
    logger.info("FinalFlatImage application stopped");
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
