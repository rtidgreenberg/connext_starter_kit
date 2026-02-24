# Foxglove GeoJSON Application

Publishes `foxglove::GeoJSON` messages for visualization in Foxglove Studio, while also subscribing to a few “control” topics (Command/Button/Config) to demonstrate multi-topic setups.

## What it does

- Publishes a GeoJSON `FeatureCollection` at ~2 Hz on the `GeoJSON` topic.
- Subscribes to `Command`, `Button`, and `Config` topics (handlers log received samples).
- Uses the shared DDS utility wrappers: `DDSParticipantSetup`, `DDSReaderSetup`, `DDSWriterSetup`.

## DDS interfaces

| Kind | Type | Topic | QoS |
|------|------|-------|-----|
| Reader | `example_types::Command` | `Command` | `qos_profiles::ASSIGNER` |
| Reader | `example_types::Button` | `Button` | `qos_profiles::ASSIGNER` |
| Reader | `example_types::Config` | `Config` | `qos_profiles::ASSIGNER` |
| Writer | `foxglove::GeoJSON` | `GeoJSON` | `qos_profiles::ASSIGNER` |

## Foxglove omg idl types

Type used is taken from [Foxglove Schemas](https://github.com/foxglove/foxglove-sdk/tree/main/schemas/omgidl/foxglove) so they are compatible with builtit Foxglove panels such as 3d, video, audio, map and others.

You can modify these types by including **keys and extra members** and Foxglove will still be able to interpret data to display in builtin panels.

## Build

Build from the repository root (this also generates the DDS types library):

```bash
export NDDSHOME=/path/to/rti_connext_dds-7.3.0
source $NDDSHOME/resource/scripts/rtisetenv_<target>.bash

cd /path/to/connext_starter_kit
mkdir -p build && cd build
cmake ..
cmake --build .
```

## Run

From the repository root:

```bash
./apps/cxx11/foxglove_geojson/run.sh
```

Common options:

```bash
./apps/cxx11/foxglove_geojson/run.sh --domain 1
./apps/cxx11/foxglove_geojson/run.sh --verbosity 1
./apps/cxx11/foxglove_geojson/run.sh --qos-file dds/qos/DDS_QOS_PROFILES.xml
```

## View in Foxglove

- Connect Foxglove to your DDS→Foxglove bridge (or your chosen transport).
- Add a panel that can render `foxglove::GeoJSON` and select the `GeoJSON` topic.

## Notes

- The published payload is a GeoJSON `FeatureCollection` (point geometry) encoded as a string field.
- If you see the topic/type but no updates, confirm your bridge is subscribed on the same DDS domain and that QoS compatibility is satisfied.