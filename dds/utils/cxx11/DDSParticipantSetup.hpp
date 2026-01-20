#ifndef DDS_PARTICIPANT_SETUP
#define DDS_PARTICIPANT_SETUP

#include <iostream>
#include <csignal>
#include <string>
#include <mutex>
#include <unordered_map>
#include <thread>
#include <chrono>

#include <rti/rti.hpp>  // include all base plus extensions
#include <rti/core/cond/AsyncWaitSet.hpp>
#include <rti/distlogger/DistLogger.hpp>

// For example legibility.
using namespace rti::all;

/*
 * DDSParticipantSetup Class
 * 
 * Manages the core DDS infrastructure for the application:
 *   - DomainParticipant: Represents the application's connection to a DDS domain
 *   - AsyncWaitSet: Centrally managed event dispatcher that handles all DDS status events
 *                   (data available, publication matched, liveliness changes, etc.) across
 *                   all readers and writers in asynchronous thread pool
 *   - QoS File Path: Stores the path to XML QoS configuration file for reuse by readers/writers
 * 
 * The AsyncWaitSet enables event-driven processing with configurable thread pool size,
 * allowing readers and writers to register status conditions and callbacks that execute
 * asynchronously when events occur.
 */
class DDSParticipantSetup {
private:
    const int _domain_id;
    std::string _qos_file_path;

    // Domain Participant
    DomainParticipant _participant = dds::core::null;

    // Async Waitset - centrally managed
    rti::core::cond::AsyncWaitSet _async_waitset = dds::core::null;

public:
    DDSParticipantSetup(
            const int domain_id,
            const int thread_pool_size = 5,
            const std::string &participant_qos_file = "",
            const std::string &participant_qos_profile = "",
            const std::string &app_name = "RTI_DDS_Application")
            : _domain_id(domain_id),
              _qos_file_path(participant_qos_file),
              _async_waitset(
                      AsyncWaitSetProperty().thread_pool_size(thread_pool_size))
    {
        try {
            if (!participant_qos_file.empty()
                && !participant_qos_profile.empty()) {
                // Create QosProvider and DomainParticipant with profile
                dds::core::QosProvider qos_provider(participant_qos_file);

                auto participant_qos =
                        qos_provider.participant_qos(participant_qos_profile);

                // Name the Participant so it's easier to track
                participant_qos
                        << rti::core::policy::EntityName().name(app_name);

                // Create Participant
                _participant = dds::domain::DomainParticipant(
                        _domain_id,
                        participant_qos);

                // Print to console before DistLogger is initialized
                std::cout << "DDSParticipantSetup created with QoS profile: "
                          << participant_qos_profile
                          << " from file: " << participant_qos_file
                          << " and Domain ID: " << domain_id << std::endl;
            } else {
                // Fallback to default
                _participant = dds::domain::DomainParticipant(1);
                std::cout << "DDSParticipantSetup created with default QoS"
                          << std::endl;
            }
        } catch (const std::exception &e) {
            std::cerr << "Failed to create DomainParticipant with QoS profile: "
                      << e.what() << std::endl;
            // Fallback to default
            _participant = dds::domain::DomainParticipant(1);
        }


    }

    ~DDSParticipantSetup()
    {
        // Stop AsyncWaitSet before destruction
        try {
            _async_waitset.stop();
        } catch (const std::exception &e) {
            std::cerr << "Error stopping AsyncWaitSet during destruction: " 
                      << e.what() << std::endl;
        }

        std::cout << "DDSParticipantSetup destroyed" << std::endl;
    }

    // Getter for Domain Participant
    DomainParticipant &participant()
    {
        return _participant;
    }

    // Getter for AsyncWaitSet
    rti::core::cond::AsyncWaitSet &async_waitset()
    {
        return _async_waitset;
    }

    // Getter for QoS file path
    const std::string &qos_file_path() const
    {
        return _qos_file_path;
    }

    // Additional public methods can be added here
};

#endif  // DDS_PARTICIPANT_SETUP