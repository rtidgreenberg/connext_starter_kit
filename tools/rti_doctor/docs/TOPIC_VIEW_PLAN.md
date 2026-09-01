# RTI Doctor Topic View Plan

## Purpose

Add a topic-first workflow to the interactive RTI Doctor UI. It lets an
operator begin with a DDS topic, see its health at a glance, understand how
its writers and readers relate, and open a direct endpoint report without
manually correlating discovery identifiers across screens.

This is an observed-topology and compatibility view. It must not claim that
two remote endpoints have formed a live middleware association when Doctor
only has passive discovery evidence.

## Entry Screen

The `DDS System Overview` opening menu has exactly three peer options:

```text
Findings   Review diagnostic issues and evidence
Topology   Browse participants, readers, and writers
Topics     Browse topic health and endpoint relationships
```

`Topics` is not nested under `Topology`. It is the direct starting point for
the operator who knows which data flow they need to inspect.

Selecting `Topics` opens the topic list. The list is sorted by health:
`ERROR`, then `WARN`, then `OK`, with topic name as the stable secondary key.
Each row shows topic name, writer count, reader count, and an explicit health
label. The label is always present; color supports it but never stands alone.

```text
Topic              Writers  Readers  Health
Telemetry                2        3  ERROR (1)
CameraImage              1        1  WARN (type unavailable)
Heartbeat                1        2  OK
```

## Topic Health

Topic health is a rollup of the existing passive `SystemScanSnapshot` issues
linked to that topic or to an endpoint on that topic.

| Health | Color | Meaning |
| --- | --- | --- |
| `ERROR` | red | An observed error affects the topic, including an RxO or partition incompatibility. |
| `WARN` | yellow | No error is present, but the evidence is incomplete or a warning affects the topic, such as unavailable or pending type information. |
| `OK` | green | No observed error or warning is linked to the topic. |

An endpoint with incomplete discovery data must not be called compatible or
incompatible. Its uncertainty is visible in the topic detail and contributes
to `WARN` when no `ERROR` is present.

## Topic Detail

Selecting a topic opens a relationship view built from the same snapshot that
supplies the health rollup. It renders three sections:

1. **Compatible groups**: each writer followed by readers for which Doctor
   observed no incompatibility in the discovery data.
2. **Unmatched writers**: writers with no compatible reader. The row states
   whether no reader was discovered, each possible pair was incompatible, or
   the evidence was incomplete.
3. **Unmatched readers**: readers with no compatible writer, using the same
   reason categories.

```text
Topic: Telemetry                                             ERROR
Observed compatibility, not live association

Compatible groups
Writer  logger / RTI Connext
  Reader dashboard / Cyclone DDS
  Reader recorder / RTI Connext

Unmatched writers
Writer  simulator / Fast DDS             RELIABILITY mismatch

Unmatched readers
Reader  archive / Cyclone DDS            type information unavailable

o Open endpoint report   f Linked findings   r Refresh   b Back
```

The relationship classifier evaluates each writer-reader pair on the selected
topic using the existing requested/offered and partition comparison. It keeps
three distinct outcomes:

- **Compatible by discovery**: no observable mismatch.
- **Incompatible by discovery**: one or more observed mismatches, named in the
  unmatched endpoint reason.
- **Indeterminate**: relevant QoS or type data cannot be evaluated. This is
  shown as incomplete evidence, not as a confirmed mismatch.

Type compatibility findings are included when they name the pair or topic, but
the view must not infer a pair-level type result that the system scan did not
produce.

## Navigation

- `Enter` on a selected endpoint opens its existing direct `ReportScreen`.
- `o` opens an endpoint chooser containing every endpoint for the topic. Each
  row includes kind, participant, vendor, type state, and health. Selecting a
  row opens its direct report.
- `f` opens only the issues linked to the selected topic.
- `r` refreshes the passive system snapshot, then recomputes health and groups.
- `b` and `Escape` return to the topic list.

The topic list and topic detail preserve the existing scan-failure convention:
the last successful snapshot stays visible and the status line explains when a
refresh failed.

## Implementation Steps

1. Add `Topics` to `SystemOverviewScreen` and route it to a new top-level topic
   list screen. Retain `Topology` and `Findings` unchanged as peer options.
2. Extract a pure topic-relationship builder beside the system scan code. Its
   inputs are the registry and a `SystemScanSnapshot`; its output is stable,
   testable topic rows and detail groups.
3. Reuse the existing topic-linked issue and severity helpers for health
   rollups. Extend them only where topic-wide findings must mark all named
   endpoints.
4. Replace the current flat `TopicEndpointsScreen` table with the grouped topic
   detail, or rename it to clarify the new responsibility.
5. Add the endpoint chooser behind `o`; reuse the current endpoint report path
   rather than creating a second report implementation.
6. Update the README navigation description and key table once the UI is
   implemented.

## Tests

Add focused unit and Textual screen tests for:

- the three opening-menu options and `Topics` routing;
- health ordering and red/yellow/green labels;
- one writer with several compatible readers;
- incompatible QoS or partition pairs appearing as unmatched with a reason;
- writer-only and reader-only topics;
- pending or unavailable type information producing indeterminate pairing and
  topic `WARN` when no error is present;
- `ERROR` taking precedence over `WARN` in the topic rollup;
- `o` listing every endpoint and opening the selected direct report;
- linked-findings filtering and refresh/failure behavior.

Run the unit tier with:

```bash
./tools/rti_doctor/run_tests.sh
```