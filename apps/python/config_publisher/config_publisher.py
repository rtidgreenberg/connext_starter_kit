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
import asyncio
import argparse
import rti.connextdds as dds
import rti.asyncio

# Add the DDS Python codegen path to Python path
_gen_dir = os.environ.get("DDS_PYTHON_GEN_DIR")
if _gen_dir and os.path.isdir(_gen_dir):
    sys.path.insert(0, _gen_dir)
else:
    sys.path.insert(
        0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "dds", "datamodel")
    )

# Import DDS Data Types, Topics and config constants
from python_gen.ExampleTypes import example_types
from python_gen.Definitions import topics, qos_profiles, domains

# Application constants
DEFAULT_APP_NAME = "Config Publisher"
DEFAULT_APP_VERSION = "1.0.0"


class ConfigPublisherApp:
    """Publishes an AppConfig sample once on startup using ParameterQoS
    (RELIABLE + TRANSIENT_LOCAL). Late-joining subscribers automatically
    receive the config sample upon discovery."""

    @staticmethod
    async def run(domain_id: int, qos_file_path: str, app_name: str):

        # Load QoS profiles from the specified file
        print(f"Loading QoS profiles from: {qos_file_path}")
        qos_provider = dds.QosProvider(qos_file_path)

        # Create DomainParticipant
        participant_qos = qos_provider.participant_qos_from_profile(
            qos_profiles.DEFAULT_PARTICIPANT
        )
        participant_qos.participant_name.name = app_name
        participant = dds.DomainParticipant(domain_id, participant_qos)

        print(f"DomainParticipant created on domain {domain_id}")

        # Create Topic
        config_topic = dds.Topic(
            participant, topics.APP_CONFIG_TOPIC, example_types.AppConfig
        )

        # Create DataWriter with ParameterQoS (RELIABLE + TRANSIENT_LOCAL)
        # This ensures late-joiners receive the config on discovery
        config_writer_qos = qos_provider.datawriter_qos_from_profile(
            qos_profiles.PARAMETER
        )
        config_writer = dds.DataWriter(
            participant.implicit_publisher, config_topic, config_writer_qos
        )

        print(f"Config writer created with QoS: {qos_profiles.PARAMETER}")

        # # Wait for writer to be matched before publishing
        # status_condition = dds.StatusCondition(config_writer)
        # status_condition.enabled_statuses = dds.StatusMask.PUBLICATION_MATCHED
        # waitset = dds.WaitSet()
        # waitset += status_condition

        # Build config sample
        config_sample = example_types.AppConfig()
        config_sample.app_id = app_name.lower().replace(" ", "_")
        config_sample.app_name = app_name
        config_sample.domain_id = domain_id
        config_sample.version = DEFAULT_APP_VERSION
        config_sample.publish_rate_hz = 0.0
        config_sample.debug_enabled = False
        config_sample.description = (
            f"{app_name} configuration published on startup"
        )

        # Wait for discovery before publishing
        print("[CONFIG] Waiting 2 seconds for discovery...")
        await asyncio.sleep(1.0)

        # Publish once on startup
        config_writer.write(config_sample)
        print(
            f"[CONFIG] Published AppConfig:"
            f" app_id={config_sample.app_id},"
            f" version={config_sample.version},"
            f" domain={config_sample.domain_id}"
        )

        # Keep alive so TRANSIENT_LOCAL serves the sample to late-joiners
        print("[CONFIG] Keeping alive for late-joiners (Ctrl+C to exit)...")
        try:
            while True:
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass

        print("[CONFIG] Shutting down.")


def main():
    parser = argparse.ArgumentParser(
        description="Config Publisher - Publishes AppConfig once on startup using ParameterQoS"
    )

    parser.add_argument(
        "-d", "--domain_id", type=int, default=1,
        help="Domain ID (default: 1)"
    )

    parser.add_argument(
        "-q", "--qos_file", type=str,
        default="../../../dds/qos/DDS_QOS_PROFILES.xml",
        help="Path to QoS profiles XML file"
    )

    parser.add_argument(
        "-n", "--name", type=str, default=DEFAULT_APP_NAME,
        help="Application name for the config"
    )

    parser.add_argument(
        "-v", "--verbosity", type=int, default=1,
        help="Logging verbosity (0=silent, 5=all)"
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
    dds.Logger.instance.verbosity = verbosity_levels.get(
        args.verbosity, dds.Verbosity.EXCEPTION
    )

    try:
        rti.asyncio.run(
            ConfigPublisherApp.run(
                domain_id=args.domain_id,
                qos_file_path=args.qos_file,
                app_name=args.name,
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
