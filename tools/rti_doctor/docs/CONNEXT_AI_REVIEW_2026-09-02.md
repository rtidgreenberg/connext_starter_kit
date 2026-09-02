# Connext AI Review - 2026-09-02

Scope: production DDS-facing code in `tools/rti_doctor/rti_doctor`.

The review combined a complete local inventory of direct DDS API use with
focused Connext AI reviews of participant lifecycle, Network Capture, probing,
QoS compatibility, built-in discovery, TypeLookup, and DynamicData usage.

## Findings and Resolution

| Priority | Finding | Resolution |
| --- | --- | --- |
| High | Network Capture was enabled after native logger and XTypes configuration, despite requiring enablement before every Connext API call. | Fixed: enablement now happens immediately after CLI/log setup and before native Connext configuration; disablement occurs after the participant closes. |
| Medium | Temporary reader/writer QoS copied liveliness kind but not lease duration. | Fixed: both probe directions now copy the discovered lease duration with the kind. |
| Medium | Creating a disabled participant temporarily changed process-global factory QoS without an explicit participant entity-factory setting or synchronization. | Fixed: the participant explicitly enables its own child cascade, and the temporary factory-QoS mutation is serialized and restored immediately after participant creation. |
| Medium | A writing probe can affect EXCLUSIVE ownership arbitration. | Fixed: synthetic writes remain opt-in, disposable, and isolated; the TUI confirmation and headless flag now explicitly disclose the ownership-arbitration risk. |
| Low | `request_types_filter="*"` is costly on very large domains. | Accepted for explicit full diagnostics: it is required to inspect arbitrary remote dynamic types. A future selective-inspection mode can narrow it by topic. |

## Confirmed Good Practices

- Built-in publication and subscription listeners are installed before the
  diagnostic participant is enabled.
- Discovery uses endpoint GUID keys and defensively handles invalid/disposed
  samples.
- TypeLookup remains enabled by default and DynamicData endpoints are created
  only when remote type information is available.
- Probe and live-feed entities use bounded lifetimes and close in `finally`.
- Irreversible `ignore_datawriter` and `ignore_datareader` calls are confined
  to disposable participants.
- Network Capture is participant-scoped and its capture is stopped before the
  captured participant is closed.

## Sources

- RTI Connext AI reviews performed 2026-09-02.
- RTI Connext Professional 7.7 Network Capture, ENTITYFACTORY, TypeLookup,
  Dynamic Types, and Requested-vs-Offered QoS documentation.