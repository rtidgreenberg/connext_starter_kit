# Foxglove PointCloud Application

Publishes `foxglove::PointCloud` messages for visualization in Foxglove Studio, along with `foxglove::FrameTransforms` to keep a frame tree alive.

## What it does

- Publishes a synthetic point cloud (sphere) at ~10 Hz on the `PointCloud` topic.
- Publishes an identity transform `world` → `lidar` on the `FrameTransform` topic.
- Subscribes to `PointCloud` (logs received samples).
- Uses the shared DDS utility wrappers: `DDSParticipantSetup`, `DDSReaderSetup`, `DDSWriterSetup`.

## DDS interfaces

| Kind | Type | Topic | QoS |
|------|------|-------|-----|
| Reader | `foxglove::PointCloud` | `PointCloud` | `qos_profiles::LARGE_DATA_SHMEM` |
| Writer | `foxglove::PointCloud` | `PointCloud` | `qos_profiles::LARGE_DATA_SHMEM` |
| Writer | `foxglove::FrameTransforms` | `FrameTransform` | `qos_profiles::LARGE_DATA_SHMEM` |

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
./apps/cxx11/foxglove_pointcloud/run.sh
```

Common options:

```bash
./apps/cxx11/foxglove_pointcloud/run.sh --domain 1
./apps/cxx11/foxglove_pointcloud/run.sh --verbosity 1
./apps/cxx11/foxglove_pointcloud/run.sh --qos-file dds/qos/DDS_QOS_PROFILES.xml
```

## View in Foxglove

- Connect Foxglove to your DDS→Foxglove bridge (or your chosen transport).
- Add a 3D panel.
- Select the `PointCloud` topic for point cloud rendering.
- Ensure the frame tree includes `world` and `lidar` (published on `FrameTransform`).

## Notes

- The point cloud uses packed float32 XYZ fields (little-endian) with `point_stride = 12`.
- If you see the topic/type but no updates, confirm your bridge can receive this topic with `qos_profiles::LARGE_DATA_SHMEM` (this profile pins the topic to SHMEM-only).