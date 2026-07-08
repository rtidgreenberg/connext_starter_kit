# rti_view — Standalone DDS Data Visualization Tool

## Overview

`rti_view` is a single-process, single-pane DDS data viewer. For v1, each instance
manages exactly one view, one topic, and one field. The active view can switch between
message field data and plot mode without changing the subscription. Multiple instances
can run in parallel for different topics or fields.

V1 is a Dear PyGui desktop tool. The copied startup command launches the same Dear
PyGui field view directly; it is not a separate web UI or terminal TUI workflow.

## Design Goals

1. **Single pane per process** — no tabs, no multi-window management; one topic and
    one selected field per v1 process.
2. **Specified-domain discovery** — search for the requested topic on the user-specified
    domain using builtin topic listeners (same pattern as `rti_spy/rtispy.py`).
3. **QoS matching** — automatically derive compatible reader/subscriber QoS from
    discovered writer QoS and report clear diagnostics if matching still fails.
4. **Dynamic data** — use `rti.connextdds` DynamicData to subscribe to propagated
    DynamicTypes without compile-time generated code.
5. **Field selection** — enumerate DynamicType members, let user pick one field to
   display or plot.
6. **Saveable startup string** — persist the user's selection (domain, topic, field,
   view mode) as a CLI invocation string that reproduces the view on next launch.

## V1 Boundaries

V1 includes:

- One Dear PyGui process with one active field view.
- One user-selected domain, one topic, and one field.
- Interactive browsing by domain → process/participant → writer topic → field.
- Direct startup by domain/topic/field/mode.
- Message Data / Plot toggle for the selected field.
- DynamicData subscriptions using types propagated through discovery.

V1 intentionally excludes:

- Multi-topic views.
- Multi-field overlays.
- Automatic domain scanning.
- Participant/process identifiers in the reusable startup command.
- External type loading from XML/IDL/generated type support.
- Web UI or terminal TUI modes.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       rti_view process                       │
├─────────────────────────────────────────────────────────────┤
│  CLI / Startup Config                                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ --domain 0 --topic "Square" --field "x" --mode plot    │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐  │
│  │  Discovery   │──▶│  Subscriber  │──▶│  View Pane    │  │
│  │  Engine      │   │  Engine      │   │  (text/plot)  │  │
│  └──────────────┘   └──────────────┘   └───────────────┘  │
│         │                    │                   │          │
│         ▼                    ▼                   ▼          │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐  │
│  │  Topic List  │   │  Field       │   │  Render Loop  │  │
│  │  (builtin    │   │  Extractor   │   │  (Dear       │  │
│  │   topics)    │   │  (DynamicType│   │   PyGui)     │  │
│  └──────────────┘   │   introspect)│   └───────────────┘  │
│                      └──────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

## Modules

| Module | Responsibility |
|--------|---------------|
| `__main__.py` | CLI entry point, arg parsing, orchestration |
| `discovery.py` | DomainParticipant creation, builtin-topic listeners, topic/endpoint registry |
| `subscriber.py` | QoS matching, DynamicData topic/reader creation, sample delivery |
| `fields.py` | DynamicType introspection, field enumeration, path-based access |
| `views/main_window.py` | Dear PyGui application shell for discovery, field selection, toggle, and plotting |
| `views/plot_view.py` | Dear PyGui plot rendering for numeric field values over time |
| `config.py` | Load/save startup strings, serialize user selections |

## Workflow

### Interactive Mode (topic/field omitted)

Default launch is an interactive selection flow. The user starts the app, picks a
domain, drills into one discovered process, selects one available writer topic,
selects one field, and then uses the top toggle to switch between message data and
plot display.

1. Start rti_view without topic/field arguments.
2. Show a domain selector (default 0, user can enter another domain).
3. Create DomainParticipant on the selected domain.
4. Attach PublicationListener + SubscriptionListener to discover participants and endpoints.
5. Present discovered DDS participants/process-like entries. In v1, "process" means
    the discovered DDS participant identity: participant name when available, plus
    participant key/IP fallback for disambiguation. Some applications may create more
    than one DDS participant, so the UI should label this clearly as Process/Participant.
6. User selects one process/participant → show available writer topics for that participant.
7. User selects one writer topic → introspect its propagated DynamicType fields.
8. User selects one field → subscribe with matched QoS and open the field view.
9. The top of the field view has a display-mode toggle: Message Data / Plot.
   Message Data prints the selected field values as samples arrive. Plot renders the
   selected numeric field over time; for non-numeric fields, Plot is disabled or shows
   a clear "field is not plottable" diagnostic.
10. Keep a startup-command bar at the bottom of the screen showing the equivalent
   command-line invocation, with a Copy button so the user can run the same view
   directly next time.

Example generated startup command:

```bash
rti_view --domain 0 --topic "SensorData" --field "temperature" --mode plot
```

### Direct View Mode (full args provided)

```bash
rti_view --domain 0 --topic "Square" --field "x" --mode plot --history 30
```

Direct view mode skips the browsing screens and opens the same Dear PyGui field view
that the interactive flow would have opened after selection.

1. Create participant on the specified domain.
2. Wait for the requested topic to appear on that domain (with timeout).
3. Verify the discovered writer propagates a usable DynamicType.
4. Verify the requested field exists in the discovered DynamicType.
5. Match QoS, subscribe, and render immediately in the requested initial mode.
6. Keep the Message Data / Plot toggle available so the user can switch modes after launch.

## Discovery Engine (from rtispy patterns)

```python
# Builtin topic listeners — same as rti_spy/rtispy.py
participant.publication_reader.set_listener(PublicationListener(), dds.StatusMask.DATA_AVAILABLE)
participant.subscription_reader.set_listener(SubscriptionListener(), dds.StatusMask.DATA_AVAILABLE)

# Endpoint registry
endpoints: dict[str, Endpoint] = {}
```

Key points from rtispy reference:
- Create the participant normally and attach listeners right after; announcements that
    arrive before attachment stay cached in the builtin readers and are picked up by
    polling (`refresh_endpoints`), so no factory QoS changes are needed.
- Refresh participant/process-like rows from `participant.discovered_participants()` and
    `participant.discovered_participant_data(handle)`.
- Use endpoint `participant_key` values from builtin publication/subscription data to
    group writer topics under the selected process/participant.
- Store discovered QoS (reliability, durability, deadline, ownership, partition, presentation).
- Store `data.type` (DynamicType) for later DynamicData subscription.
- V1 assumes systems propagate the needed DynamicType in discovery data. If a topic is
    found without a usable DynamicType, rti_view reports that the type is unavailable
    instead of attempting external type loading.

## QoS Matching (from rtispy patterns)

QoS matching is automatic but not guaranteed. rti_view copies the discovered writer's
communication-relevant QoS into the local reader/subscriber where appropriate, then
reports why subscription setup or matching failed if Connext still rejects the match.
Possible failure causes include missing propagated type information, incompatible
security or transport configuration, conflicting endpoint QoS, discovery timeout, or
multiple writers on the same topic with different offered QoS.

```python
# Match subscriber partition to writer's partition
subscriber_qos = dds.SubscriberQos()
if endpoint.partition:
    subscriber_qos.partition.name = endpoint.partition.name

# Match reader QoS to writer's offered QoS
reader_qos = dds.DataReaderQos()
reader_qos.reliability.kind = endpoint.reliability.kind
reader_qos.durability.kind = endpoint.durability.kind
if endpoint.deadline:
    reader_qos.deadline.period = endpoint.deadline.period
if endpoint.ownership:
    reader_qos.ownership.kind = endpoint.ownership.kind
```

## Field Extraction (DynamicType introspection)

Field selection is built from the discovered `DynamicType`, not by probing live
sample values. rti_view walks the full type member-by-member, builds dot-separated
field paths such as `position.x`, and then uses those paths to read values from
incoming `DynamicData` samples.

Accessor contract for v1:

- Type traversal: `dynamic_type.member_count` + `dynamic_type.member(index)`, or
  `dynamic_type.members()` when available.
- Member metadata: `member.name`, `member.type`, `member.type.kind`.
- Sample field read: `sample[field_path]`, including nested paths like
  `sample["position.x"]`.
- Sample top-level field list: `sample.fields()` is useful for inspection, but field
  catalogs should still come from the discovered `DynamicType` so nested fields and
  plottability are known before samples arrive.

```python
def enumerate_fields(dynamic_type: dds.DynamicType, prefix: str = "") -> list[FieldDescriptor]:
    """Recursively enumerate scalar fields from a DynamicType."""
    fields = []
    for index in range(dynamic_type.member_count):
        member = dynamic_type.member(index)
        path = f"{prefix}.{member.name}" if prefix else member.name
        member_type = member.type
        if is_scalar(member_type):
            fields.append(FieldDescriptor(path=path, name=member.name, type=member_type))
        elif is_struct(member_type):
            fields.extend(enumerate_fields(member_type, prefix=path))
    return fields

def read_field(sample: dds.DynamicData, field_path: str):
    return sample[field_path]
```

## Startup String Format

```
rti_view -d <domain> -t <topic_name> -f <field_path> -m <text|plot> [--history <seconds>] [--direct-view]
```

The copied command is regenerated whenever the user changes domain, process,
topic, field, or the Message Data / Plot toggle. Process selection is only part
of the interactive drill-down flow; the reusable command stays portable by
recording only domain, topic, field, and mode.

If multiple writers with the same topic name exist on the specified domain, v1
selects the first compatible writer it discovers for direct startup commands and
shows a diagnostic that more than one matching writer exists. Users who need a
specific writer can launch interactively and select the desired process/participant.

Examples:
```bash
# Print the 'x' field of Square topic on domain 0
rti_view -d 0 -t Square -f x -m text --direct-view

# Plot the 'temperature' field from SensorData on domain 5
rti_view -d 5 -t SensorData -f temperature -m plot --history 60 --direct-view

# Interactive mode on domain 1
rti_view -d 1
```

## Dependencies

- `rti.connextdds` — DDS connectivity, DynamicData, builtin topics
- `dearpygui` — v1 GUI shell, controls, tables/lists, text display, and live plotting

## Future Extensions

- Multiple fields on one plot (multi-series/overlay)
- CSV export of captured data
- Trigger/alarm thresholds
- Snapshot freeze/resume
- Topic filter expressions (content-filtered topics)
- External type loading from XML/IDL/generated type support for systems that do not
    propagate DynamicTypes during discovery
