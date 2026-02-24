# Foxglove GStreamer Video Application

Publishes `foxglove::CompressedVideo` messages for visualization in Foxglove Studio, using a local GStreamer pipeline to generate an H.264 test pattern.

## What it does

- Generates an H.264 stream with GStreamer (`videotestsrc` → encoder → appsink).
- Publishes one `foxglove::CompressedVideo` per frame on the `Image` topic.
- Subscribes to the same `Image` topic (logs received samples).
- Uses the shared DDS utility wrappers: `DDSParticipantSetup`, `DDSReaderSetup`, `DDSWriterSetup`.

## DDS interfaces

| Kind | Type | Topic | QoS |
|------|------|-------|-----|
| Reader | `foxglove::CompressedVideo` | `Image` | `qos_profiles::LARGE_DATA_SHMEM` |
| Writer | `foxglove::CompressedVideo` | `Image` | `qos_profiles::LARGE_DATA_SHMEM` |

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
./apps/cxx11/foxglove_gstreamvideo_app/run.sh
```

Common options:

```bash
./apps/cxx11/foxglove_gstreamvideo_app/run.sh --domain 1
./apps/cxx11/foxglove_gstreamvideo_app/run.sh --verbosity 1
./apps/cxx11/foxglove_gstreamvideo_app/run.sh --qos-file dds/qos/DDS_QOS_PROFILES.xml
```

## View in Foxglove

- Connect Foxglove to your DDS→Foxglove bridge (or your chosen transport).
- Add a Video panel (or a panel that supports `foxglove::CompressedVideo`) and select the `Image` topic.

## Notes

- Payload format is `foxglove::CompressedVideo` with `format = "h264"`.
- If you see the topic/type but no frames, double-check that your bridge can receive this topic with `qos_profiles::LARGE_DATA_SHMEM` (this profile pins the topic to SHMEM-only).