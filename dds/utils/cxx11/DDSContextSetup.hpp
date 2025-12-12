#ifndef DDS_CONTEXT_SETUP
#define DDS_CONTEXT_SETUP

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
using namespace rti::dist_logger;



class DDSContextSetup {
private:
    const int _domain_id;

    // Domain Participant
    DomainParticipant _participant = dds::core::null;

    // Async Waitset - centrally managed
    rti::core::cond::AsyncWaitSet _async_waitset = dds::core::null;

    // Distributed Logger
    DistLogger _dist_logger = dds::core::null;

public:
    DDSContextSetup(
            const int domain_id,
            const int thread_pool_size = 5,
            const std::string &participant_qos_file = "",
            const std::string &participant_qos_profile = "",
            const std::string &app_name = "RTI_DDS_Application")
            : _domain_id(domain_id),
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

                std::cout << "DDSContextSetup created with QoS profile: "
                          << participant_qos_profile
                          << " from file: " << participant_qos_file
                          << "and Domain ID: " << domain_id << std::endl;
            } else {
                // Fallback to default
                _participant = dds::domain::DomainParticipant(1);
                std::cout << "DDSContextSetup created with default QoS"
                          << std::endl;
            }
        } catch (const std::exception &e) {
            std::cerr << "Failed to create DomainParticipant with QoS profile: "
                      << e.what() << std::endl;
            // Fallback to default
            _participant = dds::domain::DomainParticipant(1);
        }

        // Setup RTI Distributed Logger
        try {
            // First, create the options to personalize Distributed Logger.
            // If no options are provided, default ones will be created.
            DistLoggerOptions options;
            options.domain_id(_domain_id);
            options.application_kind(app_name + "-DistLogger");

            // reuse application participant
            options.domain_participant(_participant);

            // Then, set the created options.
            // You can only call set_options before getting the Distributed
            // Logger instance. Once an instance has been created, attempting to
            // call set_options will throw an exception.
            DistLogger::set_options(options);

            // Instantiate Distributed Logger
            _dist_logger = DistLogger::get_instance();

            std::cout << "RTI Distributed Logger configured for domain "
                      << _domain_id << std::endl;

            // Log application startup event
            _dist_logger.info(
                    "DDSContextSetup initialized with distributed logging "
                    "enabled");
        } catch (const std::exception &ex) {
            std::cerr << "Failed to setup distributed logger: " << ex.what()
                      << std::endl;
            // Continue without distributed logging
        }

        std::cout << "AsyncWaitSet created for DDSContextSetup on domain "
                  << _domain_id << std::endl;
    }

    ~DDSContextSetup()
    {
        // Stop AsyncWaitSet before destruction
        try {
            _async_waitset.stop();
            std::cout << "AsyncWaitSet stopped during DDSContextSetup "
                         "destruction"
                      << std::endl;
        } catch (const std::exception &e) {
            std::cerr << "Error stopping AsyncWaitSet during destruction: "
                      << e.what() << std::endl;
        }

        // Give time for any pending async operations to complete
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

        // The DistLogger instance must be finalized for clean-up
        // before the the participant factory is finalized.
        DistLogger::finalize();

        // The DomainParticipant will be destroyed automatically when
        // _participant goes out of scope Don't call
        // finalize_participant_factory() here - it should be done at
        // application level after ALL DDSContextSetup instances are destroyed

        std::cout << "DDSContextSetup destroyed" << std::endl;
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

    // Getter for Distributed Logger
    DistLogger &distributed_logger()
    {
        return _dist_logger;
    }

    // Stop the AsyncWaitSet
    void stop_async_waitset()
    {
        try {
            _async_waitset.stop();
            std::cout << "AsyncWaitSet stopped for DDSContextSetup on domain "
                      << _domain_id << std::endl;
        } catch (const std::exception &e) {
            std::cerr << "Error stopping AsyncWaitSet: " << e.what()
                      << std::endl;
        }
    }

    // Explicit cleanup method - call this before destruction if needed
    void shutdown()
    {
        // Stop AsyncWaitSet first
        stop_async_waitset();

        // Give some time for async operations to complete
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

        std::cout << "DDSContextSetup shutdown initiated for domain "
                  << _domain_id << std::endl;
    }

    // Additional public methods can be added here
};

#endif  // DDS_CONTEXT_SETUP