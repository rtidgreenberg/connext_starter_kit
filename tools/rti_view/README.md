# rti_view

`rti_view` is a Dear PyGui-based DDS field viewer for RTI Connext DDS.

V1 focuses on one domain, one writer topic, one DynamicData field, and one view at a time. It discovers writer topics from DDS builtin topics, enumerates fields from discovered DynamicTypes, and can render selected field values as message data or a live plot.

## Quickstart

From the repository root, run:

```bash
./tools/rti_view/run_rti_view.sh -d 0
```

The launcher performs the normal bootstrap work for you:

- creates or rebuilds `connext_dds_env/` with Python 3.10 when needed
- installs packages from `tools/rti_view/requirements.txt`
- detects `NDDSHOME` and `RTI_LICENSE_FILE`
- starts the viewer once the environment is ready

If you already know the topic and field, you can launch directly into a
subscription path:

```bash
./tools/rti_view/run_rti_view.sh -d 0 -t Telemetry -f position.x -m plot --history 30
```

Use the detailed sections below only when you need manual setup, development
workflow notes, or compatibility details.

## Prerequisites

- Python 3.10 available as `python3.10`
- RTI Connext DDS 7.7 installation available locally
- Valid RTI license file reachable through `RTI_LICENSE_FILE` or under the detected Connext install
- A host `libstdc++` runtime new enough for the installed Dear PyGui wheel

The launcher manages the shared repository virtual environment at `connext_dds_env/`.
If the environment is missing or was created with a different Python minor
version, `run_rti_view.sh` rebuilds it with Python 3.10 and synchronizes
packages from `tools/rti_view/requirements.txt`.

If Dear PyGui installs successfully but still fails during launch, the most
common cause on older Linux hosts is a `libstdc++.so.6` / `GLIBCXX_*`
compatibility mismatch in the native Dear PyGui wheel. The launcher now prints
that import error directly so the host runtime issue is visible.

`tools/rti_view/requirements.txt` currently pins `dearpygui==1.11.1` because
that wheel imports cleanly on this host, while newer 2.x wheels require a newer
`libstdc++` runtime.

## Usage

From the repository root:

```bash
./tools/rti_view/run_rti_view.sh -d 0
```

Direct view startup strings can skip browsing when domain, topic, and field are known:

```bash
./tools/rti_view/run_rti_view.sh -d 0 -t Telemetry -f position.x -m plot --history 30
./tools/rti_view/run_rti_view.sh -d 0 -t Telemetry -f status -m text
```

What the launcher does before starting the UI:

- Prefers `~/rti_connext_dds-7.7.0`, then the newest detected Connext install
- Creates or rebuilds `connext_dds_env/` with Python 3.10
- Installs Python packages from `tools/rti_view/requirements.txt`
- Resolves `RTI_LICENSE_FILE` automatically when possible

## Startup String

The portable startup command format is:

```bash
rti_view -d <domain> -t <topic_name> -f <field_path> -m <text|plot> --history <seconds>
```

Participant identity is intentionally not part of the startup string in v1.

## Development

```bash
./connext_dds_env/bin/python -m pip install -r tools/rti_view/requirements.txt
PYTHONPATH=tools/rti_view ./connext_dds_env/bin/python -m rti_view --help
PYTHONPATH=tools/rti_view ./connext_dds_env/bin/python -m unittest discover -s tools/rti_view/test
```

The live end-to-end test starts a separate Python publisher process with a
random DynamicData topic/type, discovers it through the `rti_view` path,
subscribes, reads top-level and nested fields, and verifies the selected field
can be plotted:

```bash
PYTHONPATH=tools/rti_view ./connext_dds_env/bin/python -m unittest tools/rti_view/test/test_live_e2e_integration.py
```

It uses `NDDSHOME` and `RTI_LICENSE_FILE` when set, or attempts to use the latest
`~/rti_connext_dds-*` installation. If a DomainParticipant cannot be created, the
test skips with the Connext error message.

Architecture and implementation notes live in:

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

## Connext Version Compatibility

The discovery module installs the `rti.connext` 7.7 wheel from
`tools/rti_view/requirements.txt`, and the application imports the RTI DDS API
through the `rti.connextdds` Python module exposed by that wheel.

### Type Resolution by Remote Connext Version

| Remote Version | Type Propagation | `dynamic_type` Available | Notes |
|---|---|---|---|
| **6.1.2 / 7.3.x** | TypeObject v1 inline (SEDP) | **Yes** | Type arrives immediately with endpoint discovery |
| **7.7.0+** | TypeObject v2 via TypeLookup Service | **Yes** | `request_types_filter = "*"` is enabled with the 7.7 Python binding |

### Current Binding: `rti.connext 7.7.x` on Python 3.10

- `data.type` is populated from inline TypeObject v1 for 6.1.2/7.3.x remotes.
- `request_types_filter = "*"` is enabled when available in the 7.7 Python binding,
  allowing type resolution from 7.7.0+ remotes without local matching endpoints.
- `endpoint_type_object_lb_serialization_threshold = -1` ensures uncompressed
  TypeObject v1 acceptance for maximum interop with older remotes.
- The code imports `rti.connextdds`; the distribution package installed by pip is
  still named `rti.connext`.

### Compatibility Notes

1. **7.3.1 Shapes Demo → rti_view (7.7.x binding)**: Participant discovered,
   Square topic found, `dynamic_type = StructType (ShapeTypeExtended)` — **PASS**
2. **7.7.0 Shapes Demo → rti_view (7.7.x binding)**: Participant discovered,
  and the current 7.7 binding supports type lookup through TypeLookup Service

### Implementation Note

`configure_type_lookup_qos()` in `discovery.py` automatically sets
`request_types_filter = "*"` when the 7.7+ Python binding exposes it, enabling
type resolution from 7.7.0+ remotes.
