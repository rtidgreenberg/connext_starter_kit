# Tools

Utility tools for RTI Connext DDS development, inspection, and debugging.

## Quick Start

From the repository root:

```bash
./tools/rti_view/run_rti_view.sh -d 0
./tools/rti_spy/run_rtispy.sh --domain 1
```

Both tools use the shared repository virtual environment at `connext_dds_env/` and auto-detect `NDDSHOME` when possible.

## rti_view/

Dear PyGui-based DDS field viewer.

Use `rti_view` when you want to browse a domain by process/participant, select one writer topic, select one DynamicData field, and show that field as message data or a live plot.

```bash
./tools/rti_view/run_rti_view.sh -d 0
./tools/rti_view/run_rti_view.sh -d 0 -t Telemetry -f position.x -m plot --history 30
```

Related docs:

- [rti_view/ARCHITECTURE.md](rti_view/ARCHITECTURE.md)
- [rti_view/IMPLEMENTATION_PLAN.md](rti_view/IMPLEMENTATION_PLAN.md)

## rti_spy/

Textual-based DDS monitoring and inspection tool.

Use RTI Spy when you want a terminal UI for discovery, endpoint inspection, DynamicData topic monitoring, QoS reference behavior, or Distributed Logger support.

```bash
./tools/rti_spy/run_rtispy.sh --domain 1
./tools/rti_spy/run_rtispy.sh --domain 5 --interval 5
```

Related docs:

- [rti_spy/README.md](rti_spy/README.md)

## optimize_socket_buffers.sh

Optimizes Linux socket buffer sizes for better DDS network performance. Useful for large data transfers or high-throughput scenarios.

```bash
sudo ./tools/optimize_socket_buffers.sh
```

This sets `rmem_max` and `wmem_max` to 10 MB for improved UDP performance.

## RTI License

If the tools report a missing license, set `RTI_LICENSE_FILE` or place `rti_license.dat` under your Connext installation:

```bash
export RTI_LICENSE_FILE=/path/to/rti_license.dat
```

For RTI Connext DDS support:

- RTI Community Forums: https://community.rti.com
- RTI Documentation: https://community.rti.com/documentation
