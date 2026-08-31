# Incompatible QoS Listener Application

A Python reproducer for receiving the **`on_requested_incompatible_qos`** callback at the
**DomainParticipant level** — that is, with the listener installed on the `DomainParticipant`
rather than on the `DataReader`.

A Modern C++ counterpart lives in
[`apps/cxx11/incompatible_qos_listener/`](../../cxx11/incompatible_qos_listener/); the two
interoperate over the wire.

## Quick Start

1. **Get an RTI license** - Visit https://www.rti.com/get-connext

2. **Check your email** - You'll receive an automated email with `rti_license.dat` within minutes

3. **Set the license environment variable:**
   ```bash
   export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
   ```

4. **Run the application:**
   ```bash
   ./run.sh --domain_id 1
   ```

The app forces a QoS mismatch, waits for the callback, prints the status, and exits `0` on
success or `1` if the callback never arrived.

---

## Why this works

`REQUESTED_INCOMPATIBLE_QOS` is a **DataReader** status, but it is still reachable from a
participant listener because of the listener inheritance chain:

```
DomainParticipantListener  ->  SubscriberListener  ->  AnyDataReaderListener
```

`DomainParticipantListener` therefore inherits `on_requested_incompatible_qos`, and DDS
delivers each status to the **most local listener whose mask enables it**, walking upward:

```
DataReader  ->  Subscriber  ->  DomainParticipant
```

Two conditions must hold for the participant listener to be the one called:

1. Neither the `DataReader` nor its `Subscriber` has a listener whose mask includes
   `REQUESTED_INCOMPATIBLE_QOS`. This app installs **no** listener on either, so the status
   propagates all the way up.
2. The participant listener's mask includes `dds.StatusMask.REQUESTED_INCOMPATIBLE_QOS`.

Note that the first callback argument is the **DataReader that detected the incompatibility**,
not the `DomainParticipant`:

```python
def on_requested_incompatible_qos(self, reader, status):
    ...
```

## Which status, and on which side

This is the part that most often goes wrong, so it is worth being explicit.
`OFFERED_INCOMPATIBLE_QOS` and `REQUESTED_INCOMPATIBLE_QOS` are **not two views of the same
event**. They are different statuses raised on opposite sides of a failed match, in
**different participants**:

| Status | Bit | Entity that raises it | Participant that sees it |
| --- | --- | --- | --- |
| `REQUESTED_INCOMPATIBLE_QOS` | `1 << 6` | `DataReader` | the **subscribing** application's |
| `OFFERED_INCOMPATIBLE_QOS` | `1 << 5` | `DataWriter` | the **publishing** application's |

A participant listener only ever sees statuses raised by **its own contained entities**. It
cannot observe the remote application's side of the mismatch. So a participant that holds
only DataReaders will never have an offered-incompatible-qos status, no matter what its
listener implements — that status belongs to the remote writer's participant.

Masking the wrong one is silent: nothing fires, and there is no warning. If a participant
holds both readers and writers and you want either direction, enable both bits and implement
both callbacks:

```python
participant.set_listener(
    listener,
    dds.StatusMask.REQUESTED_INCOMPATIBLE_QOS | dds.StatusMask.OFFERED_INCOMPATIBLE_QOS,
)
```

This app keeps the two apart deliberately, to show which side raises which: the subscriber
participant gets `REQUESTED_INCOMPATIBLE_QOS`, the publisher participant gets
`OFFERED_INCOMPATIBLE_QOS`.

## Which listener wins

"Most local listener whose mask enables the status" is easy to state and easy to get
backwards. Measured with a reliable reader against a best-effort writer:

| Participant listener | DataReader listener | Which fired |
| --- | --- | --- |
| `REQUESTED_INCOMPATIBLE_QOS` | *(none)* | participant |
| `REQUESTED_INCOMPATIBLE_QOS` | `REQUESTED_INCOMPATIBLE_QOS` | **reader** |

Installing a participant listener does **not** steal the status from a DataReader listener
that has it enabled. If a reader listener appears to "stop firing" when you add a participant
listener, check the *reader's own mask* first — a reader whose mask does not cover the status
never had it enabled, so it propagates up; the participant listener did not take it away.

## Polling instead of listening

There is no participant-level equivalent to `reader.requested_incompatible_qos_status` — it is
not a participant status, and there is no aggregated participant-wide status object.
To poll, enumerate the endpoints and poll each:

```python
for subscriber in participant.find_subscribers():
    for reader in subscriber.find_datareaders():
        status = reader.requested_incompatible_qos_status

for publisher in participant.find_publishers():
    for writer in publisher.find_datawriters():
        status = writer.offered_incompatible_qos_status
```

## How the app is built

```python
class QosMismatchParticipantListener(dds.NoOpDomainParticipantListener):
    def on_requested_incompatible_qos(self, reader, status):
        ...

listener = QosMismatchParticipantListener()

# Installed at construction; participant.set_listener(listener, mask) works too.
participant = dds.DomainParticipant(
    domain_id,
    participant_qos,
    listener,
    dds.StatusMask.REQUESTED_INCOMPATIBLE_QOS,
)
```

`NoOpDomainParticipantListener` is the convenient base class: it supplies empty bodies for
every callback, so only the ones you care about need overriding.

**Listener lifetime**: keep a Python reference to the listener for as long as the participant
lives. Here `run()` holds it in a local for the whole call; in a longer-lived application
store it as an attribute next to the participant.

**Entity lifetime**: the reader and writer need no explicit handling — DDS entities are
reference types owned by their participant, and `participant.close()` tears down the
contained entities with it. (`del reader` / `del writer` would only drop a local name binding;
it is not a DDS delete.) What does matter is that the close runs on the way out even if entity
creation raises partway, so the body sits in a `try`/`finally`.

**Callback threading**: participant listener callbacks can be entered by several Connext
threads at once, so the counters are guarded by a `threading.Lock` rather than relying on the
GIL for `+= 1`. `requested_event.set()` is called from a `finally` block: because the
middleware swallows exceptions raised in a callback, a failure while printing would otherwise
be reported as a timeout rather than as the error it is.

By default the app runs both sides in one process, using two participants (a subscriber
participant that owns the listener and a publisher participant that owns the mismatched
writer), so a single command reproduces the callback end to end.

## Status object API notes

The status members verified against the **Connext 7.7.0** Python binding:

| Member | Notes |
| --- | --- |
| `status.last_policy` | The offending policy class, e.g. `rti.connextdds.Reliability`. Not `last_policy_id`. |
| `status.policies` | Sequence of `QosPolicyCount`, each with `.policy` and `.count`. Not `.policy_id`. |
| `status.total_count_change` | Property on both status types. |
| `status.total_count` | **A bound method** on `RequestedIncompatibleQosStatus`, but a plain **property** on `OfferedIncompatibleQosStatus`. |

That last row is an inconsistency in the 7.7.0 binding, so `print_status()` normalizes it:

```python
total_count = status.total_count
if callable(total_count):
    total_count = total_count()
```

Also worth knowing: an exception raised inside a listener callback is swallowed by the
middleware. It surfaces only as an `ASSERT REMOTE DW ... LC:Discovery` error line in the
Connext log, and the rest of your callback body never runs — which looks exactly like the
callback not firing at all. Keep callback bodies defensive.

## Command-line options

| Option | Default | Description |
| --- | --- | --- |
| `-d`, `--domain_id` | `1` | Domain ID |
| `-q`, `--qos_file` | `../../../dds/qos/DDS_QOS_PROFILES.xml` | QoS profiles XML |
| `-t`, `--topic` | `Position` | Topic name |
| `-p`, `--policy` | `reliability` | Which policy to make incompatible: `reliability`, `durability`, `deadline`, `ownership` |
| `-m`, `--mode` | `both` | `both` (one process), `subscriber`, or `publisher` |
| `--timeout` | `10` | Seconds to wait for the callback |
| `-v`, `--verbosity` | `1` | Connext logging verbosity (0-5) |

### The mismatches

| `--policy` | DataReader requests | DataWriter offers |
| --- | --- | --- |
| `reliability` | `RELIABLE` | `BEST_EFFORT` |
| `durability` | `TRANSIENT_LOCAL` | `VOLATILE` |
| `deadline` | period `1s` | period `5s` |
| `ownership` | `SHARED` | `EXCLUSIVE` |

## Running

Single process, both sides:

```bash
./run.sh --domain_id 1
./run.sh --domain_id 1 --policy durability
```

Two processes — start the publisher first, then the subscriber in another terminal:

```bash
./run.sh --domain_id 1 --mode publisher       # terminal 1
./run.sh --domain_id 1 --mode subscriber      # terminal 2
```

In `--mode publisher` the same listener is installed on the publishing participant with
`OFFERED_INCOMPATIBLE_QOS`, demonstrating the writer-side counterpart also arriving at the
participant level.

## Expected output

```
[SUBSCRIBER] Reader created on topic 'Position'
[SUBSCRIBER] Participant listener mask: 00000000000000000000000001000000
[PUBLISHER] Writer created on topic 'Position'
[MAIN] Forcing a 'reliability' QoS mismatch on domain 1
[MAIN] Waiting up to 10.0s for the participant callback...
[PARTICIPANT_LISTENER] on_requested_incompatible_qos
  Reader topic: Position
  Total count: 1
  Total count change: 1
  Last policy: <class 'rti.connextdds.Reliability'>
  Policy <class 'rti.connextdds.Reliability'>: 1 mismatch(es)
[RESULT] PASS - on_requested_incompatible_qos fired 1 time(s) at the participant level.
```

## Troubleshooting

**No callback fires.** In order of how often it turns out to be the cause:

1. **Wrong status for the side you are on.** A participant holding DataReaders raises
   `REQUESTED_INCOMPATIBLE_QOS`, never `OFFERED_INCOMPATIBLE_QOS` — the offered status is
   raised in the *remote* writer's participant. Masking `OFFERED_INCOMPATIBLE_QOS` on a
   reader-side participant enables a bit that is never set, and fails silently. See
   [Which status, and on which side](#which-status-and-on-which-side).
2. **A more local listener is consuming it.** Check that the `DataReader` and its
   `Subscriber` have no listener covering the status.
3. Both sides really are on the same domain and topic.

**Callback fires but prints nothing past a certain line.** An exception in the callback is
swallowed; re-run with `-v 2` or higher and look for `ASSERT REMOTE DW` in the Connext log.

For general setup and license issues, see [../README.md](../README.md).
