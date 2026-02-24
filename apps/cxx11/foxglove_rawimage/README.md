# Foxglove RawImage Application

Publishes `foxglove::RawImage` messages for visualization in Foxglove Studio, while also subscribing to the same image topic to demonstrate publish + subscribe in one process.

## What it does

- Publishes a simulated RGB image (`foxglove::RawImage`) at ~100 Hz on the `Image` topic.
- Subscribes to `Image` (handler logs received samples).
- Uses the shared DDS utility wrappers: `DDSParticipantSetup`, `DDSReaderSetup`, `DDSWriterSetup`.

## DDS interfaces

| Kind | Type | Topic | QoS |
|------|------|-------|-----|
| Reader | `foxglove::RawImage` | `Image` | `qos_profiles::LARGE_DATA_SHMEM` |
| Writer | `foxglove::RawImage` | `Image` | `qos_profiles::LARGE_DATA_SHMEM` |

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
./apps/cxx11/foxglove_rawimage/run.sh
```

Common options:

```bash
./apps/cxx11/foxglove_rawimage/run.sh --domain 1
./apps/cxx11/foxglove_rawimage/run.sh --verbosity 1
./apps/cxx11/foxglove_rawimage/run.sh --qos-file dds/qos/DDS_QOS_PROFILES.xml
```

## View in Foxglove

- Connect Foxglove to your DDS→Foxglove bridge (or your chosen transport).
- Add an **Image** panel (or any panel that can render `foxglove::RawImage`) and select the `Image` topic.

## Notes

- The publisher generates a 640x480 `rgb8` image (about 900 KB) and fills it with a simple pattern.
- This example uses `qos_profiles::LARGE_DATA_SHMEM`, which pins communication to shared memory transport. If you see discovery (topic/type) but no updates in Foxglove, verify your bridge/peer is also configured for SHMEM with compatible limits (or switch endpoints to a QoS that allows UDP).