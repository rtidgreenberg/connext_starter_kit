# (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

import time
import sys
import os
import asyncio
import argparse
import rti.connextdds as dds
import rti.asyncio

# Add the DDS Python codegen path to Python path
# Prefer versioned types from DDS_PYTHON_GEN_DIR (set by run.sh)
_gen_dir = os.environ.get("DDS_PYTHON_GEN_DIR")
if _gen_dir and os.path.isdir(_gen_dir):
    sys.path.insert(0, _gen_dir)
else:
    # Fallback: use the checked-in types in dds/datamodel/
    sys.path.insert(
        0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "dds", "datamodel")
    )

# Import DDS Data Types, Topics and config constants
from python_gen.ExampleTypes import example_types
from python_gen.Definitions import topics, qos_profiles, domains

# Application constants
PUBLISHER_SLEEP_INTERVAL = 2  # seconds for button/config publishing
# Published well above the downsampled_reader's 1Hz time-based filter so that
# app visibly demonstrates the downsampling (DataPatternsLibrary::Status1HzQoS).
POSITION_PUBLISH_INTERVAL = 0.1  # seconds (10Hz) for position publishing
MAIN_TASK_SLEEP_INTERVAL = 5  # seconds
DEFAULT_APP_NAME = "Example Python IO App"

async def process_command_data(reader):
    """Process incoming Command data"""
    # Print data as it arrives, suspending the coroutine until data is
    # available.
    async for data in reader.take_data_async():
        # Take all available command samples
        print(f"[COMMAND_SUBSCRIBER] Command Received:")
        print(f"  Command ID: {data.command_id}")
        print(f"  Destination ID: {data.destination_id}")
        print(f"  Command Type: {data.command_type}")
        print(f"  Message: {data.message}")
        print(f"  Urgent: {data.urgent}")


class ExampleIOApp:

    @staticmethod
    async def run(domain_id: int, qos_file_path: str):

        app_name = DEFAULT_APP_NAME

        # Load QoS profiles from the specified file
        print(f"Loading QoS profiles from: {qos_file_path}")
        qos_provider = dds.QosProvider(qos_file_path)

        # A DomainParticipant allows an application to begin communicating in
        # a DDS domain. Typically there is one DomainParticipant per application.
        # DomainParticipant QoS is configured in DDS_QOS_PROFILES.xml
        participant_qos = qos_provider.participant_qos_from_profile(
            qos_profiles.DEFAULT_PARTICIPANT
        )

        participant_qos.participant_name.name = app_name
        participant = dds.DomainParticipant(domain_id, participant_qos)

        print(
            f"DomainParticipant created with QoS profile: {qos_profiles.DEFAULT_PARTICIPANT}"
        )
        print(f"DOMAIN ID: {domain_id}")

        # Create Topics
        command_topic = dds.Topic(
            participant, topics.COMMAND_TOPIC, example_types.Command
        )

        button_topic = dds.Topic(participant, topics.BUTTON_TOPIC, example_types.Button)
        position_topic = dds.Topic(
            participant, topics.POSITION_TOPIC, example_types.Position
        )

        # Create DataReaders with QoS configured from DDS_QOS_PROFILES.xml
        # Using set_topic_data_reader_qos APUI allows us to use the external Assign QoS Profile
        # Otherwise can just use the regular datareader_qos_from_profile API
        command_reader_qos = qos_provider.set_topic_datareader_qos(
            qos_profiles.ASSIGNER, topics.COMMAND_TOPIC
        )
        command_reader = dds.DataReader(
            participant.implicit_subscriber, command_topic, command_reader_qos
        )

        # Create DataWriters with QoS configured from DDS_QOS_PROFILES.xml
        position_writer_qos = qos_provider.set_topic_datawriter_qos(
            qos_profiles.ASSIGNER, topics.POSITION_TOPIC
        )
        position_writer = dds.DataWriter(
            participant.implicit_publisher, position_topic, position_writer_qos
        )

        button_writer_qos = qos_provider.set_topic_datawriter_qos(
            qos_profiles.ASSIGNER, topics.BUTTON_TOPIC
        )
        button_writer = dds.DataWriter(
            participant.implicit_publisher, button_topic, button_writer_qos
        )

        print("[SUBSCRIBER] RTI Asyncio reader configured for Command data...")
        print(
            "[PUBLISHER] RTI Asyncio writers configured for Position and Button data..."
        )

        # Publisher coroutine for Position, published fast enough to
        # demonstrate the downsampled_reader's 1Hz time-based filter
        async def position_publisher_task():

            while True:
                try:
                    position_sample = example_types.Position()
                    position_sample.source_id = app_name
                    position_sample.latitude = 37.7749
                    position_sample.longitude = -122.4194
                    position_sample.altitude = 15.0
                    position_sample.timestamp_sec = int(time.time())

                    position_writer.write(position_sample)
                    print(
                        f"[POSITION_PUBLISHER] Published Position - Source: {position_sample.source_id}, Lat: {position_sample.latitude}, Lon: {position_sample.longitude}, Alt: {position_sample.altitude}"
                    )

                    await asyncio.sleep(POSITION_PUBLISH_INTERVAL)

                except asyncio.CancelledError:
                    print("[POSITION_PUBLISHER] Position publisher task cancelled")
                    break
                except Exception as e:
                    print(f"[POSITION_PUBLISHER] Error publishing data: {e}")
                    await asyncio.sleep(POSITION_PUBLISH_INTERVAL)

            print("[POSITION_PUBLISHER] Position publisher task finished.")

        # Publisher coroutine for Button, Config
        async def button_publisher_task():

            button_count = 0

            while True:
                try:
                    current_time = int(time.time())

                    # Publish Button message
                    button_sample = example_types.Button()
                    button_sample.source_id = app_name
                    button_sample.button_id = "btn_1"
                    button_sample.button_state = (
                        example_types.ButtonState.PRESSED
                    )
                    button_sample.press_count = button_count
                    button_sample.last_press_timestamp_sec = current_time
                    button_sample.hold_duration_sec = 0.0

                    button_writer.write(button_sample)
                    print(
                        f"[BUTTON_PUBLISHER] Published Button - ID: {button_sample.button_id}, Count: {button_count}"
                    )

                    button_count += 1

                    await asyncio.sleep(PUBLISHER_SLEEP_INTERVAL)

                except asyncio.CancelledError:
                    print("[BUTTON_PUBLISHER] Button publisher task cancelled")
                    break
                except Exception as e:
                    print(f"[BUTTON_PUBLISHER] Error publishing data: {e}")
                    await asyncio.sleep(PUBLISHER_SLEEP_INTERVAL)

            print("[BUTTON_PUBLISHER] Button publisher task finished.")

        # Main application coroutine
        async def main_task():
            count = 0
            while True:
                print(f"[MAIN] ExampleIOApp processing loop - iteration {count}")

                count += 1
                await asyncio.sleep(MAIN_TASK_SLEEP_INTERVAL)

        # Create and run concurrent tasks using RTI asyncio
        print("[MAIN] Starting RTI asyncio tasks...")
        try:
            await asyncio.gather(
                position_publisher_task(),
                button_publisher_task(),
                process_command_data(command_reader),
                main_task(),
            )
        except KeyboardInterrupt:
            print("[MAIN] Shutting down RTI asyncio tasks...")


def main():
    """Main entry point for the example_io_app application."""
    parser = argparse.ArgumentParser(
        description="Example I/O Application - Publishes Position/Button/Config, Subscribes to Command"
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
        rti.asyncio.run(ExampleIOApp.run(domain_id=args.domain_id, qos_file_path=args.qos_file))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
