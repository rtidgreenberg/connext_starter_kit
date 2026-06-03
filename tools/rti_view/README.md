# rti_view

`rti_view` is a Dear PyGui-based DDS field viewer for RTI Connext DDS.

V1 focuses on one domain, one writer topic, one DynamicData field, and one view at a time. It discovers writer topics from DDS builtin topics, enumerates fields from discovered DynamicTypes, and can render selected field values as message data or a live plot.

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

## Startup String

The portable startup command format is:

```bash
rti_view -d <domain> -t <topic_name> -f <field_path> -m <text|plot> --history <seconds>
```

Participant identity is intentionally not part of the startup string in v1.

## Development

```bash
PYTHONPATH=tools/rti_view python -m rti_view --help
PYTHONPATH=tools/rti_view python -m unittest discover -s tools/rti_view/test
```

The live end-to-end test starts a separate Python publisher process with a
random DynamicData topic/type, discovers it through the `rti_view` path,
subscribes, reads top-level and nested fields, and verifies the selected field
can be plotted:

```bash
PYTHONPATH=tools/rti_view python -m unittest tools/rti_view/test/test_live_e2e_integration.py
```

It uses `NDDSHOME` and `RTI_LICENSE_FILE` when set, or attempts to use the latest
`~/rti_connext_dds-*` installation. If a DomainParticipant cannot be created, the
test skips with the Connext error message.

Architecture and implementation notes live in:

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

## Connext Version Compatibility

The discovery module uses the RTI Connext Python API (`rti.connext` package) to
discover remote participants, endpoints, and their DynamicTypes via builtin topics.

### Type Resolution by Remote Connext Version

| Remote Version | Type Propagation | `dynamic_type` Available | Notes |
|---|---|---|---|
| **6.1.2 / 7.3.x** | TypeObject v1 inline (SEDP) | **Yes** | Type arrives immediately with endpoint discovery |
| **7.7.0+** | TypeObject v2 via TypeLookup Service | **No** (with 7.6.0 binding) | Requires `request_types_filter` (not in 7.6.0 binding) |

### Current Binding: `rti.connext 7.6.0`

- `data.type` is populated from inline TypeObject v1 — works for 6.1.2/7.3.x remotes.
- `request_types_filter` is **not available** in the 7.6.0 Python binding.
- `enabled_builtin_channels = ALL` enables the TypeLookup Service channel, but
  without `request_types_filter` or a local matching endpoint, types from 7.7.0+
  remotes are never resolved.
- `endpoint_type_object_lb_serialization_threshold = -1` ensures uncompressed
  TypeObject v1 acceptance for maximum interop with older remotes.

### Tested Scenarios (2026-05-29)

1. **7.3.1 Shapes Demo → rti_view (7.6.0 binding)**: Participant discovered,
   Square topic found, `dynamic_type = StructType (ShapeTypeExtended)` — **PASS**
2. **7.7.0 Shapes Demo → rti_view (7.6.0 binding)**: Participant discovered,
   Square topic found, `dynamic_type = None` — **KNOWN LIMITATION**

### Upgrade Path

When the Python binding is upgraded to 7.7.0+, `configure_type_lookup_qos()` in
`discovery.py` will automatically set `request_types_filter = "*"` (guarded by
`try/except AttributeError`), enabling type resolution from 7.7.0+ remotes.
