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

/*
 * Reproducer: on_requested_incompatible_qos at the DomainParticipant level.
 *
 * REQUESTED_INCOMPATIBLE_QOS is a DataReader status, but
 * dds::domain::DomainParticipantListener inherits it through
 * dds::sub::SubscriberListener -> dds::sub::AnyDataReaderListener, so the status
 * propagates DataReader -> Subscriber -> DomainParticipant and is delivered to
 * the most local listener whose mask enables it. This app installs the listener
 * *only* on the participant, leaves the DataReader and Subscriber without
 * listeners, and forces a QoS mismatch so the participant-level callback fires.
 */

#include <iostream>
#include <string>
#include <memory>
#include <mutex>
#include <condition_variable>
#include <chrono>

// include both the standard APIs and extensions
#include <rti/rti.hpp>
#include <rti/config/Logger.hpp>

#include "application.hpp"  // for command line parsing and ctrl-c
#include "ExampleTypes.hpp"
#include "Definitions.hpp"

const std::string APP_NAME = "Incompatible QoS Listener";

// ---------------------------------------------------------------------------
// QosPolicyId is a plain uint32_t, so map it back to a readable policy name
// using the dds::core::policy::policy_id / policy_name traits.
// ---------------------------------------------------------------------------
template <typename Policy>
bool match_policy_name(
    dds::core::policy::QosPolicyId id,
    std::string& name)
{
    if (dds::core::policy::policy_id<Policy>::value == id) {
        name = dds::core::policy::policy_name<Policy>::name();
        return true;
    }
    return false;
}

std::string policy_id_to_name(dds::core::policy::QosPolicyId id)
{
    using namespace dds::core::policy;

    std::string name;
    if (match_policy_name<Reliability>(id, name)) return name;
    if (match_policy_name<Durability>(id, name)) return name;
    if (match_policy_name<Deadline>(id, name)) return name;
    if (match_policy_name<Ownership>(id, name)) return name;
    if (match_policy_name<LatencyBudget>(id, name)) return name;
    if (match_policy_name<Liveliness>(id, name)) return name;
    if (match_policy_name<DestinationOrder>(id, name)) return name;
    if (match_policy_name<Presentation>(id, name)) return name;
    if (match_policy_name<Partition>(id, name)) return name;

    return "QosPolicyId " + std::to_string(id);
}

// ---------------------------------------------------------------------------
// The participant-level listener. Deriving from NoOpDomainParticipantListener
// supplies empty bodies for every other callback, so only the two of interest
// need overriding.
// ---------------------------------------------------------------------------
class QosMismatchParticipantListener
        : public dds::domain::NoOpDomainParticipantListener {
public:
    // Called on a Connext middleware thread, not the main thread. An exception
    // escaping a listener callback is swallowed by the middleware, so keep the
    // body defensive.
    void on_requested_incompatible_qos(
        dds::sub::AnyDataReader& reader,
        const dds::core::status::RequestedIncompatibleQosStatus& status) override
    {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            requested_count_++;
            requested_received_ = true;
        }

        std::cout << "[PARTICIPANT_LISTENER] on_requested_incompatible_qos"
                  << std::endl;
        std::cout << "  Reader topic: " << reader.topic_name() << std::endl;
        print_status(status.total_count(), status.total_count_change(),
                     status.last_policy_id(), status.policies());

        condition_.notify_all();
    }

    // The DataWriter-side counterpart, also delivered at the participant.
    void on_offered_incompatible_qos(
        dds::pub::AnyDataWriter& writer,
        const dds::core::status::OfferedIncompatibleQosStatus& status) override
    {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            offered_count_++;
        }

        std::cout << "[PARTICIPANT_LISTENER] on_offered_incompatible_qos"
                  << std::endl;
        std::cout << "  Writer topic: " << writer.topic_name() << std::endl;
        print_status(status.total_count(), status.total_count_change(),
                     status.last_policy_id(), status.policies());
    }

    // Waits for the requested-incompatible-qos callback, or until the timeout
    // elapses or Ctrl-C is pressed.
    bool wait_for_requested(double timeout_sec)
    {
        auto deadline = std::chrono::steady_clock::now()
            + std::chrono::milliseconds(static_cast<long>(timeout_sec * 1000));

        std::unique_lock<std::mutex> lock(mutex_);
        while (!requested_received_ && !application::shutdown_requested) {
            if (condition_.wait_until(lock, deadline) == std::cv_status::timeout) {
                break;
            }
        }
        return requested_received_;
    }

    int requested_count()
    {
        std::lock_guard<std::mutex> lock(mutex_);
        return requested_count_;
    }

private:
    static void print_status(
        int32_t total_count,
        int32_t total_count_change,
        dds::core::policy::QosPolicyId last_policy_id,
        const dds::core::policy::QosPolicyCountSeq& policies)
    {
        std::cout << "  Total count: " << total_count << std::endl;
        std::cout << "  Total count change: " << total_count_change << std::endl;
        std::cout << "  Last policy: " << policy_id_to_name(last_policy_id)
                  << " (id " << last_policy_id << ")" << std::endl;
        for (const auto& policy_count : policies) {
            std::cout << "  Policy " << policy_id_to_name(policy_count.policy_id())
                      << ": " << policy_count.count() << " mismatch(es)"
                      << std::endl;
        }
    }

    std::mutex mutex_;
    std::condition_variable condition_;
    bool requested_received_ = false;
    int requested_count_ = 0;
    int offered_count_ = 0;
};

// ---------------------------------------------------------------------------
// The mismatches: the reader requests something the writer will not offer.
// ---------------------------------------------------------------------------
void apply_reader_mismatch(
    const std::string& policy,
    dds::sub::qos::DataReaderQos& reader_qos)
{
    using namespace dds::core::policy;

    if (policy == "reliability") {
        reader_qos << Reliability::Reliable();
    } else if (policy == "durability") {
        reader_qos << Reliability::Reliable();
        reader_qos << Durability::TransientLocal();
    } else if (policy == "deadline") {
        // A reader deadline stricter (shorter) than the writer's is incompatible.
        reader_qos << Deadline(dds::core::Duration(1));
    } else if (policy == "ownership") {
        reader_qos << Ownership::Shared();
    }
}

void apply_writer_mismatch(
    const std::string& policy,
    dds::pub::qos::DataWriterQos& writer_qos)
{
    using namespace dds::core::policy;

    if (policy == "reliability") {
        writer_qos << Reliability::BestEffort();
    } else if (policy == "durability") {
        writer_qos << Reliability::Reliable();
        writer_qos << Durability::Volatile();
    } else if (policy == "deadline") {
        writer_qos << Deadline(dds::core::Duration(5));
    } else if (policy == "ownership") {
        writer_qos << Ownership::Exclusive();
    }
}

// ---------------------------------------------------------------------------

int run(const application::ApplicationArguments& args)
{
    const bool run_subscriber =
        args.mode == "both" || args.mode == "subscriber";
    const bool run_publisher =
        args.mode == "both" || args.mode == "publisher";

    std::cout << "Loading QoS profiles from: " << args.qos_file_path << std::endl;
    dds::core::QosProvider qos_provider(args.qos_file_path);

    auto listener = std::make_shared<QosMismatchParticipantListener>();

    // The listener is installed on the participant that owns the endpoint whose
    // status we want to observe.
    const auto sub_mask = dds::core::status::StatusMask::requested_incompatible_qos();
    const auto pub_mask = dds::core::status::StatusMask::offered_incompatible_qos();

    // DDS entities are reference types with their own shared ownership, so they
    // are declared directly and initialized to dds::core::null until the
    // selected mode creates them. Wrapping them in a smart pointer would only
    // add a second, redundant ownership layer.
    dds::domain::DomainParticipant sub_participant = dds::core::null;
    dds::domain::DomainParticipant pub_participant = dds::core::null;
    dds::sub::DataReader<example_types::Position> reader = dds::core::null;
    dds::pub::DataWriter<example_types::Position> writer = dds::core::null;

    if (run_subscriber) {
        auto participant_qos =
            qos_provider.participant_qos(qos_profiles::DEFAULT_PARTICIPANT);
        participant_qos
            << rti::core::policy::EntityName(APP_NAME + " Subscriber");

        sub_participant =
            dds::domain::DomainParticipant(args.domain_id, participant_qos);

        // set_listener() takes a shared_ptr; the participant keeps it alive.
        sub_participant.set_listener(listener, sub_mask);

        dds::topic::Topic<example_types::Position> topic(
            sub_participant, args.topic_name);

        // No listener on the Subscriber and none on the DataReader, so the
        // status propagates up to the participant listener. The Subscriber
        // handle may leave scope; the DataReader keeps its parent alive.
        dds::sub::Subscriber subscriber(sub_participant);
        auto reader_qos = subscriber.default_datareader_qos();
        apply_reader_mismatch(args.policy, reader_qos);

        reader = dds::sub::DataReader<example_types::Position>(
            subscriber, topic, reader_qos);

        std::cout << "[SUBSCRIBER] Reader created on topic '"
                  << args.topic_name << "'" << std::endl;
    }

    if (run_publisher) {
        auto participant_qos =
            qos_provider.participant_qos(qos_profiles::DEFAULT_PARTICIPANT);
        participant_qos
            << rti::core::policy::EntityName(APP_NAME + " Publisher");

        pub_participant =
            dds::domain::DomainParticipant(args.domain_id, participant_qos);

        if (!run_subscriber) {
            pub_participant.set_listener(listener, pub_mask);
        }

        dds::topic::Topic<example_types::Position> topic(
            pub_participant, args.topic_name);

        dds::pub::Publisher publisher(pub_participant);
        auto writer_qos = publisher.default_datawriter_qos();
        apply_writer_mismatch(args.policy, writer_qos);

        writer = dds::pub::DataWriter<example_types::Position>(
            publisher, topic, writer_qos);

        std::cout << "[PUBLISHER] Writer created on topic '"
                  << args.topic_name << "'" << std::endl;
    }

    std::cout << "[MAIN] Forcing a '" << args.policy
              << "' QoS mismatch on domain " << args.domain_id << std::endl;

    int exit_code = 0;

    if (run_subscriber) {
        std::cout << "[MAIN] Waiting up to " << args.timeout_sec
                  << "s for the participant callback..." << std::endl;

        if (listener->wait_for_requested(args.timeout_sec)) {
            std::cout << "[RESULT] PASS - on_requested_incompatible_qos fired "
                      << listener->requested_count()
                      << " time(s) at the participant level." << std::endl;
        } else {
            std::cout << "[RESULT] FAIL - no on_requested_incompatible_qos "
                      << "callback within " << args.timeout_sec
                      << "s. Check that a mismatched writer is running on the "
                      << "same domain and topic." << std::endl;
            exit_code = 1;
        }
    } else {
        // Publisher-only: hold the writer up so a separate subscriber process
        // can discover it and report the mismatch.
        std::cout << "[PUBLISHER] Holding the writer open. Ctrl-C to exit."
                  << std::endl;
        while (!application::shutdown_requested) {
            rti::util::sleep(dds::core::Duration::from_millisecs(200));
        }
        std::cout << "[PUBLISHER] Shutting down." << std::endl;
    }

    // Not required for teardown -- destroying a participant releases the
    // listener shared_ptr on its own, and this listener holds no entity
    // reference that could form a cycle. It is done anyway so that callbacks
    // stop deterministically here, rather than printing after the result line.
    if (sub_participant != dds::core::null) {
        sub_participant.set_listener(nullptr);
    }
    if (pub_participant != dds::core::null) {
        pub_participant.set_listener(nullptr);
    }

    return exit_code;
}

int main(int argc, char *argv[])
{
    using namespace application;

    ApplicationArguments args = parse_arguments(argc, argv);
    if (args.parse_result == ParseReturn::exit) {
        return EXIT_SUCCESS;
    } else if (args.parse_result == ParseReturn::failure) {
        return EXIT_FAILURE;
    }

    setup_signal_handlers();

    // Sets Connext verbosity to help debugging
    rti::config::Logger::instance().verbosity(args.verbosity);

    int exit_code = EXIT_FAILURE;
    try {
        exit_code = run(args);
    } catch (const std::exception& ex) {
        std::cerr << "Exception in run(): " << ex.what() << std::endl;
        exit_code = EXIT_FAILURE;
    }

    // Releases the memory used by the participant factory. Optional at
    // application shutdown.
    dds::domain::DomainParticipant::finalize_participant_factory();

    return exit_code;
}
