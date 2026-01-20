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
PUBLISHER_SLEEP_INTERVAL = 1  # seconds for image publishing (simulating 1 Hz)
MAIN_TASK_SLEEP_INTERVAL = 5  # seconds
DEFAULT_APP_NAME = "Large Data Python App"
IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
IMAGE_SIZE = IMAGE_WIDTH * IMAGE_HEIGHT * 3  # RGB format (3 bytes per pixel) = ~921KB

async def process_image_data(reader):
    """Process incoming Image data"""
    # Print data as it arrives, suspending the coroutine until data is
    # available.
    async for data in reader.take_data_async():
        # Take all available image samples
        print(f"[IMAGE_SUBSCRIBER] Image Received:")
        print(f"  Image ID: {data.image_id}")
        print(f"  Width: {data.width}")
        print(f"  Height: {data.height}")
        print(f"  Format: {data.format}")
        print(f"  Data Size: {len(data.data)} bytes")

        # Log image data
        distlog.Logger.info(
            f"Received Image data - id:{data.image_id}, size:{len(data.data)} bytes, {data.width}x{data.height}"
        )


class LargeDataApp:

    @staticmethod
    async def run(domain_id: int, qos_file_path: str):

        app_name = DEFAULT_APP_NAME

        # Load QoS profiles from the specified file
        print(f"Loading QoS profiles from: {qos_file_path}")
        qos_provider = dds.QosProvider(qos_file_path)

        # Create DomainParticipant with LARGE_DATA_PARTICIPANT QoS profile
        # This profile is optimized for large data transfers with shared memory
        participant_qos = qos_provider.participant_qos_from_profile(
            qos_profiles.LARGE_DATA_PARTICIPANT
        )

        participant_qos.participant_name.name = app_name
        participant = dds.DomainParticipant(domain_id, participant_qos)

        print(
            f"DomainParticipant created with QoS profile: {qos_profiles.LARGE_DATA_PARTICIPANT}"
        )
        print(f"DOMAIN ID: {domain_id}")

        # Initialize RTI Distributed Logger using the existing participant
        # This ensures the logger uses the same large data configuration
        logger_options = distlog.LoggerOptions()
        logger_options.domain_id = domain_id
        logger_options.application_kind = app_name + "-DistLogger"
        logger_options.participant = participant
        distlog.Logger.init(logger_options)
        print(f"RTI Distributed Logger configured using existing participant")
        distlog.Logger.info("LargeDataApp initialized with distributed logging enabled")

        # Create Image Topic
        image_topic = dds.Topic(participant, topics.IMAGE_TOPIC, example_types.Image)

        # Create DataReader with LARGE_DATA_SHMEM QoS for large data over shared memory
        image_reader_qos = qos_provider.set_topic_datareader_qos(
            qos_profiles.LARGE_DATA_SHMEM, topics.IMAGE_TOPIC
        )
        image_reader = dds.DataReader(
            participant.implicit_subscriber, image_topic, image_reader_qos
        )

        # Create DataWriter with LARGE_DATA_SHMEM QoS for large data over shared memory
        image_writer_qos = qos_provider.set_topic_datawriter_qos(
            qos_profiles.LARGE_DATA_SHMEM, topics.IMAGE_TOPIC
        )
        image_writer = dds.DataWriter(
            participant.implicit_publisher, image_topic, image_writer_qos
        )

        print("[SUBSCRIBER] RTI Asyncio reader configured for Image data (Large Data with SHMEM)...")
        print("[PUBLISHER] RTI Asyncio writer configured for Image data (Large Data with SHMEM)...")

        # Publisher coroutine for Image
        async def publisher_task():

            image_count = 0

            while True:
                try:
                    current_time = int(time.time())

                    # Publish Image message with large data payload
                    image_sample = example_types.Image()
                    image_sample.image_id = f"img_{image_count:06d}"
                    image_sample.width = IMAGE_WIDTH
                    image_sample.height = IMAGE_HEIGHT
                    image_sample.format = "RGB"
                    
                    # Create simulated image data (pattern based on count for variety)
                    # In real application, this would be actual camera/sensor data
                    pattern_value = (image_count % 256)
                    image_sample.data = [pattern_value] * IMAGE_SIZE

                    image_writer.write(image_sample)
                    print(
                        f"[IMAGE_PUBLISHER] Published Image - ID: {image_sample.image_id}, Size: {len(image_sample.data)} bytes"
                    )
                    distlog.Logger.info(
                        f"Published Image - id:{image_sample.image_id}, size:{len(image_sample.data)} bytes, {IMAGE_WIDTH}x{IMAGE_HEIGHT}"
                    )

                    image_count += 1

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
                print(f"[MAIN] LargeDataApp processing loop - iteration {count}")
                distlog.Logger.info(f"Large Data processing loop - iteration: {count}")

                count += 1
                await asyncio.sleep(MAIN_TASK_SLEEP_INTERVAL)

        # Create and run concurrent tasks using RTI asyncio
        print("[MAIN] Starting RTI asyncio tasks...")
        try:
            await asyncio.gather(
                publisher_task(), process_image_data(image_reader), main_task()
            )
        except KeyboardInterrupt:
            print("[MAIN] Shutting down RTI asyncio tasks...")
            distlog.Logger.warning("Application shutdown requested by user")
        finally:
            # Finalize distributed logger
            print("[MAIN] Finalizing distributed logger...")
            distlog.Logger.finalize()


def main():
    """Main entry point for the large_data_app application."""
    parser = argparse.ArgumentParser(
        description="Large Data Application - Publishes and Subscribes to Image data using Large Data QoS"
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
        rti.asyncio.run(LargeDataApp.run(domain_id=args.domain_id, qos_file_path=args.qos_file))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
