# (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

"""Reproducer: on_requested_incompatible_qos at the DomainParticipant level.

REQUESTED_INCOMPATIBLE_QOS is a DataReader status, but DomainParticipantListener
inherits it (DomainParticipantListener -> SubscriberListener ->
AnyDataReaderListener), so the status propagates DataReader -> Subscriber ->
DomainParticipant and is delivered to the most local listener whose mask enables
it. This app installs the listener *only* on the participant, leaves the
DataReader and Subscriber without listeners, and forces a QoS mismatch so the
participant-level callback fires.
"""

import sys
import os
import argparse
import threading
import rti.connextdds as dds

# Add the DDS Python codegen path to Python path
_gen_dir = os.environ.get("DDS_PYTHON_GEN_DIR")
if not _gen_dir or not os.path.isdir(_gen_dir):
    raise RuntimeError(
        "DDS_PYTHON_GEN_DIR is not configured. Run this application through run.sh "
        "or initialize generated Python type support first."
    )
sys.path.insert(0, _gen_dir)

# Import DDS Data Types, Topics and config constants
from python_gen.ExampleTypes import example_types
from python_gen.Definitions import topics, qos_profiles

# Application constants
DEFAULT_APP_NAME = "Incompatible QoS Listener"
DEFAULT_TOPIC = topics.POSITION_TOPIC


def apply_reader_mismatch(policy: str, reader_qos):
    """Make the reader request something the writer will not offer."""
    if policy == "reliability":
        reader_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
    elif policy == "durability":
        reader_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
        reader_qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    elif policy == "deadline":
        # A reader deadline stricter (shorter) than the writer's is incompatible.
        reader_qos.deadline.period = dds.Duration(1)
    elif policy == "ownership":
        reader_qos.ownership.kind = dds.OwnershipKind.SHARED
    return reader_qos


def apply_writer_mismatch(policy: str, writer_qos):
    """Make the writer offer less than the reader requests."""
    if policy == "reliability":
        writer_qos.reliability.kind = dds.ReliabilityKind.BEST_EFFORT
    elif policy == "durability":
        writer_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
        writer_qos.durability.kind = dds.DurabilityKind.VOLATILE
    elif policy == "deadline":
        writer_qos.deadline.period = dds.Duration(5)
    elif policy == "ownership":
        writer_qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
    return writer_qos


# Define the participant-level listener by inheriting from
# NoOpDomainParticipantListener so only the callbacks of interest are overridden.
class QosMismatchParticipantListener(dds.NoOpDomainParticipantListener):

    def __init__(self):
        super().__init__()
        # The callbacks run on Connext middleware threads, not the main thread,
        # and a participant listener may be entered by several of them at once,
        # so the counters are guarded rather than relying on the GIL.
        self.requested_event = threading.Event()
        self._lock = threading.Lock()
        self._requested_count = 0
        self._offered_count = 0

    def on_requested_incompatible_qos(self, reader, status):
        """DataReader status delivered at the DomainParticipant level.

        An exception raised here is swallowed by the middleware and only shows
        up as an ASSERT REMOTE DW log line, so the event is set from a finally
        block: a failure while printing must not turn into a reported timeout.
        """
        try:
            with self._lock:
                self._requested_count += 1
            print("[PARTICIPANT_LISTENER] on_requested_incompatible_qos")
            print(f"  Reader topic: {reader.topic_name}")
            self.print_status(status)
        finally:
            # Set last so the detail above is flushed before the main thread
            # wakes and prints the result line.
            self.requested_event.set()

    def on_offered_incompatible_qos(self, writer, status):
        """The DataWriter-side counterpart, also delivered at the participant."""
        with self._lock:
            self._offered_count += 1
        print("[PARTICIPANT_LISTENER] on_offered_incompatible_qos")
        print(f"  Writer topic: {writer.topic_name}")
        self.print_status(status)

    def requested_count(self):
        with self._lock:
            return self._requested_count

    @staticmethod
    def print_status(status):
        # total_count is a bound method on RequestedIncompatibleQosStatus but a
        # plain property on OfferedIncompatibleQosStatus (Connext 7.7.0 Python
        # binding), so normalize before printing.
        total_count = status.total_count
        if callable(total_count):
            total_count = total_count()
        print(f"  Total count: {total_count}")
        print(f"  Total count change: {status.total_count_change}")
        # The offending policy is status.last_policy; each entry of
        # status.policies is a QosPolicyCount with .policy and .count.
        print(f"  Last policy: {status.last_policy}")
        for policy_count in status.policies:
            print(f"  Policy {policy_count.policy}: {policy_count.count} mismatch(es)")


class IncompatibleQosListenerApp:

    @staticmethod
    def create_participant(domain_id, qos_provider, name, listener=None, mask=None):
        participant_qos = qos_provider.participant_qos_from_profile(
            qos_profiles.DEFAULT_PARTICIPANT
        )
        participant_qos.participant_name.name = name

        if listener is None:
            return dds.DomainParticipant(domain_id, participant_qos)

        # The listener may be installed either at construction, as here, or
        # afterwards with participant.set_listener(listener, mask).
        return dds.DomainParticipant(domain_id, participant_qos, listener, mask)

    @staticmethod
    def run(domain_id, qos_file_path, topic_name, policy, mode, timeout):

        print(f"Loading QoS profiles from: {qos_file_path}")
        qos_provider = dds.QosProvider(qos_file_path)

        listener = QosMismatchParticipantListener()
        run_subscriber = mode in ("both", "subscriber")
        run_publisher = mode in ("both", "publisher")

        # The listener is installed on the participant that owns the endpoint
        # whose status we want to observe.
        sub_mask = dds.StatusMask.REQUESTED_INCOMPATIBLE_QOS
        pub_mask = dds.StatusMask.OFFERED_INCOMPATIBLE_QOS

        participants = []
        received = False

        # DDS entities are reference types owned by the participant, so there
        # is nothing to hold on the reader and writer beyond keeping them in
        # scope. The try/finally is what matters: it guarantees deterministic
        # shutdown even if entity creation raises partway through.
        try:
            if run_subscriber:
                sub_participant = IncompatibleQosListenerApp.create_participant(
                    domain_id,
                    qos_provider,
                    f"{DEFAULT_APP_NAME} Subscriber",
                    listener,
                    sub_mask,
                )
                participants.append(sub_participant)

                sub_topic = dds.Topic(
                    sub_participant, topic_name, example_types.Position
                )
                reader_qos = apply_reader_mismatch(
                    policy, sub_participant.default_datareader_qos
                )
                # No listener on the DataReader and none on the Subscriber, so the
                # status propagates up to the participant listener.
                reader = dds.DataReader(
                    sub_participant.implicit_subscriber, sub_topic, reader_qos
                )
                print(f"[SUBSCRIBER] Reader created on topic '{topic_name}'")
                print(f"[SUBSCRIBER] Participant listener mask: {sub_mask}")

            if run_publisher:
                pub_participant = IncompatibleQosListenerApp.create_participant(
                    domain_id,
                    qos_provider,
                    f"{DEFAULT_APP_NAME} Publisher",
                    listener if not run_subscriber else None,
                    pub_mask,
                )
                participants.append(pub_participant)

                pub_topic = dds.Topic(
                    pub_participant, topic_name, example_types.Position
                )
                writer_qos = apply_writer_mismatch(
                    policy, pub_participant.default_datawriter_qos
                )
                writer = dds.DataWriter(
                    pub_participant.implicit_publisher, pub_topic, writer_qos
                )
                print(f"[PUBLISHER] Writer created on topic '{topic_name}'")

            print(f"[MAIN] Forcing a '{policy}' QoS mismatch on domain {domain_id}")

            if run_subscriber:
                print(f"[MAIN] Waiting up to {timeout}s for the participant callback...")
                received = listener.requested_event.wait(timeout)
                if received:
                    print(
                        f"[RESULT] PASS - on_requested_incompatible_qos fired "
                        f"{listener.requested_count()} time(s) at the participant level."
                    )
                else:
                    print(
                        "[RESULT] FAIL - no on_requested_incompatible_qos callback "
                        f"within {timeout}s. Check that a mismatched writer is "
                        "running on the same domain and topic."
                    )
            else:
                # Publisher-only: hold the writer up so a separate subscriber process
                # can discover it and report the mismatch.
                print("[PUBLISHER] Holding the writer open. Ctrl-C to exit.")
                received = True
                try:
                    threading.Event().wait()
                except KeyboardInterrupt:
                    print("[PUBLISHER] Shutting down.")

        finally:
            # close() tears down the participant's contained entities too, so
            # the reader and writer need no separate handling.
            for participant in participants:
                participant.close()

        return 0 if received else 1


def main():
    """Main entry point for the incompatible_qos_listener application."""
    parser = argparse.ArgumentParser(
        description="Reproducer for on_requested_incompatible_qos at the "
        "DomainParticipant level"
    )

    parser.add_argument(
        "-v", "--verbosity", type=int, default=1, help="Logging Verbosity"
    )

    parser.add_argument(
        "-d", "--domain_id", type=int, default=1, help="Domain ID (default: 1)"
    )

    parser.add_argument(
        "-q", "--qos_file", type=str, default="../../../dds/qos/DDS_QOS_PROFILES.xml",
        help="Path to QoS profiles XML file (default: ../../../dds/qos/DDS_QOS_PROFILES.xml)"
    )

    parser.add_argument(
        "-t", "--topic", type=str, default=DEFAULT_TOPIC,
        help=f"Topic name (default: {DEFAULT_TOPIC})"
    )

    parser.add_argument(
        "-p", "--policy", type=str, default="reliability",
        choices=["reliability", "durability", "deadline", "ownership"],
        help="Which QoS policy to make incompatible (default: reliability)"
    )

    parser.add_argument(
        "-m", "--mode", type=str, default="both",
        choices=["both", "subscriber", "publisher"],
        help="Run both sides in one process, or only one side (default: both)"
    )

    parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="Seconds to wait for the callback (default: 10)"
    )

    args = parser.parse_args()

    verbosity_levels = {
        0: dds.Verbosity.SILENT,
        1: dds.Verbosity.EXCEPTION,
        2: dds.Verbosity.WARNING,
        3: dds.Verbosity.STATUS_LOCAL,
        4: dds.Verbosity.STATUS_REMOTE,
        5: dds.Verbosity.STATUS_ALL,
    }

    # Sets verbosity for Connext Internals to help debugging
    verbosity = verbosity_levels.get(args.verbosity, dds.Verbosity.EXCEPTION)
    dds.Logger.instance.verbosity = verbosity

    try:
        return IncompatibleQosListenerApp.run(
            domain_id=args.domain_id,
            qos_file_path=args.qos_file,
            topic_name=args.topic,
            policy=args.policy,
            mode=args.mode,
            timeout=args.timeout,
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
