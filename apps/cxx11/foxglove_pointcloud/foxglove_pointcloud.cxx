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
#include <cmath>
#include <cstring>
#include <thread>
#include <chrono>
#include <atomic>
#include <vector>

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
#include "PointCloud.hpp"
#include "FrameTransforms.hpp"

// For example legibility.
using namespace rti::all;
using namespace rti::dist_logger;

constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;
const std::string APP_NAME = "Large Data CXX FOXGLOVE";

// Image dimensions for large data transfer
constexpr uint32_t IMAGE_WIDTH = 640;
constexpr uint32_t IMAGE_HEIGHT = 480;
constexpr uint32_t IMAGE_SIZE = IMAGE_WIDTH * IMAGE_HEIGHT * 3;  // RGB format
                                                                 // (~900 KB)


// Write a little-endian float into buf at byte offset
static void pack_float32(std::vector<uint8_t>& buf, size_t offset, float value)
{
    std::memcpy(buf.data() + offset, &value, sizeof(float));
}

void process_pointcloud_data(dds::sub::DataReader<::foxglove::PointCloud> reader)
{
    auto samples = reader.take();
    for (const auto &sample : samples) {
        // Check if message is not DDS metadata
        if (sample.info().valid()) {
            // Do something with data message
            std::cout << "[POINT_SUBSCRIBER] Pointcloud Received:" << std::endl;
            
            // overloaded -> operator to use RTI extension
            std::cout << "  Topic: " << reader->topic_name() << std::endl;
        }
    }
}


void run(std::shared_ptr<DDSParticipantSetup> participant_setup)
{
    auto& rti_logger = rti::config::Logger::instance();

    rti_logger.notice(
            "Large Data application starting...");

    // DDSReaderSetup and DDSWriterSetup are example wrapper classes for your
    // convenience that simplify DDS reader/writer creation and event handling.
    // They manage DataReader/DataWriter lifecycle, attach status conditions to
    // the centralized AsyncWaitSet, and provide convenient methods to register
    // callbacks for DDS events (data_available, subscription_matched,
    // liveliness_changed, etc.)

    // Setup Reader Interface with LARGE_DATA_SHMEM QoS
    auto point_reader = std::make_shared<DDSReaderSetup<::foxglove::PointCloud>>(
            participant_setup,
            topics::POINT_CLOUD_TOPIC,
            qos_profiles::LARGE_DATA_SHMEM);

    // Setup Writer Interface with LARGE_DATA_SHMEM QoS
    auto point_writer = std::make_shared<DDSWriterSetup<::foxglove::PointCloud>>(
            participant_setup,
            topics::POINT_CLOUD_TOPIC,
            qos_profiles::LARGE_DATA_SHMEM);

    auto transform_writer = std::make_shared<DDSWriterSetup<::foxglove::FrameTransforms>>(
            participant_setup,
            topics::TRANSFORM_TOPIC,
            qos_profiles::LARGE_DATA_SHMEM);

    // Enable Asynchronous Event-Driven processing for reader
    point_reader->set_data_available_handler(process_pointcloud_data);

    rti_logger.notice(
            "Large Data app is running. Press Ctrl+C to stop.");
    rti_logger.notice(
            "Subscribing to Image messages with LARGE_DATA_SHMEM QoS...");
    rti_logger.notice(
            "Publishing Image messages with LARGE_DATA_SHMEM QoS...");

// Build a static world -> lidar identity transform (published once per frame
    // to keep the frame tree alive during recording)
    ::foxglove::FrameTransform world_to_lidar;
    world_to_lidar.parent_frame_id("world");
    world_to_lidar.child_frame_id("lidar");

    ::foxglove::Vector3 tf_translation;
    tf_translation.x(0.0);
    tf_translation.y(0.0);
    tf_translation.z(0.0);
    world_to_lidar.translation(tf_translation);

    ::foxglove::Quaternion tf_rotation;
    tf_rotation.x(0.0);
    tf_rotation.y(0.0);
    tf_rotation.z(0.0);
    tf_rotation.w(1.0); // identity
    world_to_lidar.rotation(tf_rotation);

    // -----------------------------------------------------------------------
    // Point layout: x, y, z each as float32 (4 bytes) → 12 bytes per point
    // -----------------------------------------------------------------------
    const uint32_t POINT_STRIDE = 12;

    std::vector<::foxglove::PackedElementField> fields(3);
    fields[0].name("x");
    fields[0].offset(0);
    fields[0].type(::foxglove::NumericType::FLOAT32);

    fields[1].name("y");
    fields[1].offset(4);
    fields[1].type(::foxglove::NumericType::FLOAT32);

    fields[2].name("z");
    fields[2].offset(8);
    fields[2].type(::foxglove::NumericType::FLOAT32);

    // -----------------------------------------------------------------------
    // Demo geometry: sphere sampled on a latitude/longitude grid
    // -----------------------------------------------------------------------
    const int LAT_STEPS = 30;   // points from pole to pole
    const int LON_STEPS = 60;   // points around the equator
    const int NUM_POINTS = LAT_STEPS * LON_STEPS;
    const float RADIUS = 2.0f;

    // Identity pose: cloud origin at the world origin, no rotation
    ::foxglove::Vector3 position;
    position.x(0.0);
    position.y(0.0);
    position.z(0.0);

    ::foxglove::Quaternion orientation;
    orientation.x(0.0);
    orientation.y(0.0);
    orientation.z(0.0);
    orientation.w(1.0);

    ::foxglove::Pose pose;
    pose.position(position);
    pose.orientation(orientation);

    // Pre-fill the fields that do not change between frames
    ::foxglove::PointCloud cloud;
    cloud.frame_id("lidar");
    cloud.pose(pose);
    cloud.point_stride(POINT_STRIDE);
    cloud.fields(fields);
    uint32_t samples_written = 0;

    while (!application::shutdown_requested) {
        try {
            // Timestamp derived from wall-clock sample index at 10 Hz
        ::foxglove::Time timestamp;
        timestamp.sec(static_cast<int32_t>(samples_written / 10));
        timestamp.nsec(static_cast<uint32_t>((samples_written % 10) * 100000000u));
        cloud.timestamp(timestamp);

        // Rotate the sphere slightly each frame for a live animation effect
        const float angle_offset = samples_written * 0.05f;

        std::vector<uint8_t> data(static_cast<size_t>(NUM_POINTS) * POINT_STRIDE);

        int point_idx = 0;
        for (int lat = 0; lat < LAT_STEPS; ++lat) {
            // phi: 0 (north pole) → π (south pole)
            float phi = static_cast<float>(M_PI) * lat / (LAT_STEPS - 1);
            for (int lon = 0; lon < LON_STEPS; ++lon) {
                // theta: 0 → 2π, shifted by angle_offset for rotation
                float theta = 2.0f * static_cast<float>(M_PI) * lon / LON_STEPS
                              + angle_offset;

                float x = RADIUS * std::sin(phi) * std::cos(theta);
                float y = RADIUS * std::sin(phi) * std::sin(theta);
                float z = RADIUS * std::cos(phi);

                size_t byte_offset = static_cast<size_t>(point_idx) * POINT_STRIDE;
                pack_float32(data, byte_offset,     x);
                pack_float32(data, byte_offset + 4, y);
                pack_float32(data, byte_offset + 8, z);

                ++point_idx;
            }
        }

        cloud.data(data);

        // Publish the identity transform with the same timestamp so the 3D
        // panel always has an up-to-date frame tree entry for "lidar"
        world_to_lidar.timestamp(timestamp);
        ::foxglove::FrameTransforms tf_msg;
        tf_msg.transforms({ world_to_lidar });
        transform_writer->writer().write(tf_msg);

        std::cout << "Writing ::foxglove::PointCloud, count " << samples_written
                  << " (" << NUM_POINTS << " points, "
                  << data.size() << " bytes)" << std::endl;

        point_writer->writer().write(cloud);

    } catch (const std::exception &ex) {
        rti_logger.error(
            ("Failed to publish image: " + std::string(ex.what()))
            .c_str());
        }
        
        // Alternate Option: Use Polling Method to Read Data
        // Latency contingent on loop rate
        // process_pointcloud_data(point_reader->reader());
        
        // Publish at 10 Hz
        rti::util::sleep(dds::core::Duration(0, 100000000));
    }

    rti_logger.notice(
            "Large Data application shutting down...");

    rti_logger.notice("Large Data application stopped");
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
                qos_profiles::LARGE_DATA_PARTICIPANT,
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
