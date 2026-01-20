# (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

import sys
import os
import argparse
import rti.connextdds as dds
import rti.asyncio
import rti.logging.distlog as distlog

# Add the DDS Python codegen path to Python path
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "dds", "datamodel")
)

# Import DDS Data Types, Topics and config constants
from python_gen.ExampleTypes import example_types
from python_gen.Definitions import topics, qos_profiles

# Application constants
DEFAULT_APP_NAME = "Downsampled Position Reader"


# Define custom listener by inheriting from DataReaderListener
class PositionReaderListener(dds.DataReaderListener):
    def on_requested_deadline_missed(self, reader, status):
        """Callback for when requested deadline is missed"""
        print(f"[DEADLINE_MISSED] Publisher failed to send data within deadline period!")
        print(f"  Total count: {status.total_count}")
        print(f"  Total count change: {status.total_count_change}")
        print(f"  Last instance handle: {status.last_instance_handle}")
        distlog.Logger.warning(
            f"Requested deadline missed - total: {status.total_count}, change: {status.total_count_change}"
        )
    
    def on_subscription_matched(self, reader, status):
        """Callback for when subscription is matched or unmatched with a publication"""
        if status.current_count_change > 0:
            print(f"[SUBSCRIPTION_MATCHED] Matched with a new publisher!")
            print(f"  Current count: {status.current_count}")
            print(f"  Current count change: {status.current_count_change}")
            print(f"  Last publication handle: {status.last_publication_handle}")
            distlog.Logger.info(
                f"Subscription matched - publishers: {status.current_count}"
            )
        elif status.current_count_change < 0:
            print(f"[SUBSCRIPTION_UNMATCHED] Lost connection to a publisher!")
            print(f"  Current count: {status.current_count}")
            print(f"  Current count change: {status.current_count_change}")
            distlog.Logger.warning(
                f"Subscription unmatched - publishers: {status.current_count}"
            )
    
    def on_liveliness_changed(self, reader, status):
        """Callback for when liveliness of a matched publication changes"""
        if status.alive_count_change > 0:
            print(f"[LIVELINESS_GAINED] Publisher became alive!")
            print(f"  Alive count: {status.alive_count}")
            print(f"  Not alive count: {status.not_alive_count}")
            print(f"  Last publication handle: {status.last_publication_handle}")
            distlog.Logger.info(
                f"Liveliness gained - alive publishers: {status.alive_count}"
            )
        elif status.not_alive_count_change > 0:
            print(f"[LIVELINESS_LOST] Publisher lost liveliness!")
            print(f"  Alive count: {status.alive_count}")
            print(f"  Not alive count: {status.not_alive_count}")
            print(f"  Last publication handle: {status.last_publication_handle}")
            distlog.Logger.warning(
                f"Liveliness lost - not alive publishers: {status.not_alive_count}"
            )


async def process_position_data(reader):
    """Process incoming Position data with 1Hz downsampling"""
    async for data in reader.take_data_async():
        print(f"[POSITION_SUBSCRIBER] Position Received:")
        print(f"  Source ID: {data.source_id}")
        print(f"  Latitude: {data.latitude}")
        print(f"  Longitude: {data.longitude}")
        print(f"  Altitude: {data.altitude}")
        print(f"  Timestamp: {data.timestamp_sec}")

        distlog.Logger.info(
            f"Received Position data - source:{data.source_id}, lat:{data.latitude}, lon:{data.longitude}"
        )


class DownsampledReaderApp:

    @staticmethod
    async def run(domain_id: int, qos_file_path: str):

        app_name = DEFAULT_APP_NAME

        # Load QoS profiles from the specified file
        print(f"Loading QoS profiles from: {qos_file_path}")
        qos_provider = dds.QosProvider(qos_file_path)

        # Create DomainParticipant with DEFAULT_PARTICIPANT QoS profile
        participant_qos = qos_provider.participant_qos_from_profile(
            qos_profiles.DEFAULT_PARTICIPANT
        )

        participant_qos.participant_name.name = app_name
        participant = dds.DomainParticipant(domain_id, participant_qos)

        print(
            f"DomainParticipant created with QoS profile: {qos_profiles.DEFAULT_PARTICIPANT}"
        )
        print(f"DOMAIN ID: {domain_id}")

        # Initialize RTI Distributed Logger
        logger_options = distlog.LoggerOptions()
        logger_options.domain_id = domain_id
        logger_options.application_kind = app_name + "-DistLogger"
        logger_options.participant = participant
        distlog.Logger.init(logger_options)
        print(
            f"RTI Distributed Logger configured for domain {domain_id} with application kind: {app_name}"
        )
        distlog.Logger.info("Downsampled Reader initialized with distributed logging enabled")

        # Create Position Topic
        position_topic = dds.Topic(
            participant, topics.POSITION_TOPIC, example_types.Position
        )

        # Create DataReader with Status1HzQoS profile (1Hz time-based filter)
        position_reader_qos = qos_provider.datareader_qos_from_profile(
            "DataPatternsLibrary::Status1HzQoS"
        )
        position_reader = dds.DataReader(
            participant.implicit_subscriber, 
            position_topic, 
            position_reader_qos
        )

        # Set the listener with the appropriate status mask
        listener = PositionReaderListener()
        position_reader.set_listener(
            listener, 
            dds.StatusMask.REQUESTED_DEADLINE_MISSED | 
            dds.StatusMask.SUBSCRIPTION_MATCHED |
            dds.StatusMask.LIVELINESS_CHANGED
        )

        print("[SUBSCRIBER] RTI Asyncio reader configured for Position data with 1Hz downsampling...")
        print("[SUBSCRIBER] Listener callbacks enabled:")
        print("  - on_requested_deadline_missed: Triggers if publisher stops sending data")
        print("  - on_subscription_matched: Triggers when publishers connect/disconnect")
        print("  - on_liveliness_changed: Triggers when publisher liveliness changes")

        # Process Position data
        print("[MAIN] Starting RTI asyncio tasks...")
        try:
            await process_position_data(position_reader)
        except KeyboardInterrupt:
            print("[MAIN] Shutting down RTI asyncio tasks...")
            distlog.Logger.warning("Application shutdown requested by user")
        finally:
            print("[MAIN] Finalizing distributed logger...")
            distlog.Logger.finalize()


def main():
    """Main entry point for the downsampled_reader application."""
    parser = argparse.ArgumentParser(
        description="Downsampled Position Reader - Subscribes to Position topic with 1Hz downsampling"
    )

    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        default=1,
        help="Logging Verbosity",
    )

    parser.add_argument(
        "-d", "--domain_id", type=int, default=1, help="Domain ID (default: 1)"
    )

    parser.add_argument(
        "-q", "--qos_file", type=str, default="../../../dds/qos/DDS_QOS_PROFILES.xml",
        help="Path to QoS profiles XML file (default: ../../../dds/qos/DDS_QOS_PROFILES.xml)"
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
        # Run
        rti.asyncio.run(DownsampledReaderApp.run(domain_id=args.domain_id, qos_file_path=args.qos_file))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
