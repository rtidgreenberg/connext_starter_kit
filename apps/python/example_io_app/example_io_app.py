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
import rti.logging.distlog as distlog

# Add the DDS Python codegen path to Python path
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "dds", "datamodel")
)

# Import DDS Data Types, Topics and config constants
from python_gen.ExampleTypes import example_types
from python_gen.Definitions import topics, qos_profiles, domains

# Application constants
PUBLISHER_SLEEP_INTERVAL = 2  # seconds for command/button/config publishing
MAIN_TASK_SLEEP_INTERVAL = 5  # seconds
DEFAULT_APP_NAME = "Example Python IO App"
DEFAULT_COMMAND_DESTINATION = "target_system"
DEFAULT_CONFIG_DESTINATION = "config_target"

async def process_position_data(reader):
    """Process incoming Position data"""
    # Print data as it arrives, suspending the coroutine until data is
    # available.
    async for data in reader.take_data_async():
        # Take all available position samples
        print(f"[POSITION_SUBSCRIBER] Position Received:")
        print(f"  Source ID: {data.source_id}")
        print(f"  Latitude: {data.latitude}")
        print(f"  Longitude: {data.longitude}")
        print(f"  Altitude: {data.altitude}")
        print(f"  Timestamp: {data.timestamp_sec}")

        # Log position data
        distlog.Logger.info(
            f"Received Position data - source:{data.source_id}, lat:{data.latitude}, lon:{data.longitude}, alt:{data.altitude}"
        )


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

        # Initialize RTI Distributed Logger
        logger_options = distlog.LoggerOptions()
        logger_options.domain_id = domain_id
        logger_options.application_kind = app_name + "-DistLogger"
        logger_options.participant = participant
        distlog.Logger.init(logger_options)
        print(
            f"RTI Distributed Logger configured for domain {domain_id} with application kind: {app_name}"
        )
        distlog.Logger.info("ExampleIOApp initialized with distributed logging enabled")

        # Create Topics
        command_topic = dds.Topic(
            participant, topics.COMMAND_TOPIC, example_types.Command
        )

        button_topic = dds.Topic(participant, topics.BUTTON_TOPIC, example_types.Button)
        config_topic = dds.Topic(participant, topics.CONFIG_TOPIC, example_types.Config)
        position_topic = dds.Topic(
            participant, topics.POSITION_TOPIC, example_types.Position
        )

        # Create DataReaders with QoS configured from DDS_QOS_PROFILES.xml
        # Using set_topic_data_reader_qos APUI allows us to use the external Assign QoS Profile
        # Otherwise can just use the regular datareader_qos_from_profile API
        position_reader_qos = qos_provider.set_topic_datareader_qos(
            qos_profiles.ASSIGNER, topics.POSITION_TOPIC
        )
        position_reader = dds.DataReader(
            participant.implicit_subscriber, position_topic, position_reader_qos
        )

        # Create DataWriters with QoS configured from DDS_QOS_PROFILES.xml
        command_writer_qos = qos_provider.set_topic_datawriter_qos(
            qos_profiles.ASSIGNER, topics.COMMAND_TOPIC
        )
        command_writer = dds.DataWriter(
            participant.implicit_publisher, command_topic, command_writer_qos
        )

        button_writer_qos = qos_provider.set_topic_datawriter_qos(
            qos_profiles.ASSIGNER, topics.BUTTON_TOPIC
        )
        button_writer = dds.DataWriter(
            participant.implicit_publisher, button_topic, button_writer_qos
        )

        config_writer_qos = qos_provider.set_topic_datawriter_qos(
            qos_profiles.ASSIGNER, topics.CONFIG_TOPIC
        )
        config_writer = dds.DataWriter(
            participant.implicit_publisher, config_topic, config_writer_qos
        )

        print("[SUBSCRIBER] RTI Asyncio reader configured for Position data...")
        print(
            "[PUBLISHER] RTI Asyncio writers configured for Command, Button, and Config data..."
        )

        # Publisher coroutine for Command, Button, Config
        async def publisher_task():

            command_count = 0
            button_count = 0
            config_count = 0

            while True:
                try:
                    current_time = int(time.time())

                    # Publish Command message
                    command_sample = example_types.Command()
                    command_sample.command_id = f"cmd_{command_count:04d}"
                    command_sample.destination_id = DEFAULT_COMMAND_DESTINATION
                    command_sample.command_type = (
                        example_types.CommandType.START
                    )
                    command_sample.message = f"Command from {app_name}"
                    command_sample.urgent = 0

                    command_writer.write(command_sample)
                    print(
                        f"[COMMAND_PUBLISHER] Published Command - ID: {command_sample.command_id}"
                    )
                    distlog.Logger.info(
                        f"Published Command - id:{command_sample.command_id}, type:{command_sample.command_type}"
                    )

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
                    distlog.Logger.info(
                        f"Published Button - id:{button_sample.button_id}, state:{button_sample.button_state}, count:{button_count}"
                    )

                    # Publish Config message
                    config_sample = example_types.Config()
                    config_sample.destination_id = DEFAULT_CONFIG_DESTINATION
                    config_sample.parameter_name = "update_rate"
                    config_sample.parameter_value = "1.0"
                    config_sample.numeric_value = 1.0
                    config_sample.enabled = True

                    config_writer.write(config_sample)
                    print(
                        f"[CONFIG_PUBLISHER] Published Config - Parameter: {config_sample.parameter_name}"
                    )
                    distlog.Logger.info(
                        f"Published Config - parameter:{config_sample.parameter_name}, value:{config_sample.parameter_value}"
                    )

                    command_count += 1
                    button_count += 1
                    config_count += 1

                    await asyncio.sleep(PUBLISHER_SLEEP_INTERVAL)

                except asyncio.CancelledError:
                    distlog.Logger.warning("Publisher task cancelled")
                    break
                except Exception as e:
                    print(f"[PUBLISHER] Error publishing data: {e}")
                    distlog.Logger.error(f"Error publishing data: {e}")
                    await asyncio.sleep(PUBLISHER_SLEEP_INTERVAL)

            print("[PUBLISHER] Publisher task finished.")
            distlog.Logger.info("Publisher task completed successfully")

        # Main application coroutine
        async def main_task():
            count = 0
            while True:
                print(f"[MAIN] ExampleIOApp processing loop - iteration {count}")
                distlog.Logger.info(f"Example IO processing loop - iteration: {count}")

                count += 1
                await asyncio.sleep(MAIN_TASK_SLEEP_INTERVAL)

        # Create and run concurrent tasks using RTI asyncio
        print("[MAIN] Starting RTI asyncio tasks...")
        try:
            await asyncio.gather(
                publisher_task(), process_position_data(position_reader), main_task()
            )
        except KeyboardInterrupt:
            print("[MAIN] Shutting down RTI asyncio tasks...")
            distlog.Logger.warning("Application shutdown requested by user")
        finally:
            # Finalize distributed logger
            print("[MAIN] Finalizing distributed logger...")
            distlog.Logger.finalize()


def main():
    """Main entry point for the example_io_app application."""
    parser = argparse.ArgumentParser(
        description="Example I/O Application - Publishes Command/Button/Config, Subscribes to Position"
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
