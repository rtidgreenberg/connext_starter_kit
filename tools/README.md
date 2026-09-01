# Tools

Utility tools for RTI Connext DDS development, inspection, and debugging.

## Quick Start

From the repository root:

```bash
./tools/rti_view/run_rti_view.sh -d 0
./tools/rti_spy/run_rtispy.sh --domain 1
```

Both tools use a repository-local virtual environment. Connext 7.7 uses the
newest installed supported Python from 3.10 through 3.14, retaining
`connext_dds_env/` for Python 3.10 and using an isolated versioned environment
for newer interpreters.
They run with either the public Python API package plus an RTI license file or
an activated wheel; `NDDSHOME` is optional for these Python-only tools.

For a public PyPI deployment:

```bash
RTI_PYTHON_SOURCE=pypi \
RTI_LICENSE_FILE=/secure/path/rti_license.dat \
./tools/rti_doctor/run_rti_doctor.sh
```

For an air-gapped or no-separate-license-file deployment, provide an activated
wheel from an RTI Connext installation:

```bash
RTI_PYTHON_SOURCE=activated-wheel \
RTI_PYTHON_WHEEL=/opt/rti-wheels/rti_connext_activated-<version>-cp<python>-<platform>.whl \
./tools/rti_doctor/run_rti_doctor.sh
```

The activated-wheel path is not license-free; use and redistribution remain
subject to the applicable RTI license terms.

## rti_view/

Dear PyGui-based DDS field viewer.

Use `rti_view` when you want to browse a domain by process/participant, select one writer topic, select one DynamicData field, and show that field as message data or a live plot.

```bash
./tools/rti_view/run_rti_view.sh -d 0
./tools/rti_view/run_rti_view.sh -d 0 -t Telemetry -f position.x -m plot --history 30 --direct-view
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

When using the public PyPI package, set `RTI_LICENSE_FILE` or place
`rti_license.dat` under your Connext installation:

```bash
export RTI_LICENSE_FILE=/path/to/rti_license.dat
```

An activated `rti.connext.activated` wheel does not need separate
`RTI_LICENSE_FILE` configuration.

For RTI Connext DDS support:

- RTI Community Forums: https://community.rti.com
- RTI Documentation: https://community.rti.com/documentation

## rti_doctor

DDS **interoperability diagnostic**. Discovers participants from any DDS vendor on
a domain and reports why communication fails - blind spots in our own config,
participant/endpoint discovery gaps, unresolvable remote types, QoS
incompatibility between live endpoints, and member-level deserialization failures.
Produces a shareable plain-text report.

```bash
./tools/rti_doctor/run_rti_doctor.sh                      # interactive TUI
./tools/rti_doctor/run_rti_doctor.sh -d 1 -t MyTopic      # headless, one topic
./tools/rti_doctor/run_rti_doctor.sh -d 1 --system -o out.txt  # assess the system
```

See [tools/rti_doctor/README.md](rti_doctor/README.md).

## rti_debug_game

DDS troubleshooting scenarios with editable generated participant scripts and a
Textual Mission Contract view. Use Admin Console on game-owned domain `42` to
inspect the intended fault, repair the generated script, and run a verification
round.

```bash
./tools/rti_debug_game/run_rti_debug_game.sh
./tools/rti_debug_game/run_rti_debug_game.sh --run --level L01
```

See [rti_debug_game/README.md](rti_debug_game/README.md).
