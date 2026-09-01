# Incompatible QoS Listener Application

A Modern C++ (C++11) reproducer for receiving the **`on_requested_incompatible_qos`**
callback at the **DomainParticipant level** — that is, with the listener installed on the
`dds::domain::DomainParticipant` rather than on the `DataReader`.

This is the C++ counterpart of
[`apps/python/incompatible_qos_listener/`](../../python/incompatible_qos_listener/); the two
interoperate over the wire.

## Quick Start

```bash
./run.sh --domain 1
```

The app forces a QoS mismatch, waits for the callback, prints the status, and exits `0` on
success or `1` if the callback never arrived.

---

## Why this works

`REQUESTED_INCOMPATIBLE_QOS` is a **DataReader** status, but it is still reachable from a
participant listener because of the listener inheritance chain:

```
dds::domain::DomainParticipantListener
    -> dds::sub::SubscriberListener
        -> dds::sub::AnyDataReaderListener
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
2. The participant listener's mask includes
   `dds::core::status::StatusMask::requested_incompatible_qos()`.

Because the callback arrives through `AnyDataReaderListener`, the first parameter is
`dds::sub::AnyDataReader&` — the **type-erased reader that detected the incompatibility**,
not the `DomainParticipant`, and not a typed `dds::sub::DataReader<T>&`. That is the usual
snag when moving a callback down from the reader to the participant: the
`DataReaderListener<T>` override takes `DataReader<T>&`, but the participant-level override
must take `AnyDataReader&` or it silently fails to override anything.

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

Masking the wrong one is silent: nothing fires, and there is no warning. Same participant,
same mismatch, only the mask changed (measured against Connext 7.3.1):

| Participant listener mask | Result |
| --- | --- |
| `offered_incompatible_qos()` | **nothing fires** |
| `requested_incompatible_qos()` | `on_requested_incompatible_qos` fires |
| `all()` | `on_requested_incompatible_qos` fires |

If one participant holds both readers and writers and you want to catch either direction, OR
the two bits together and implement both callbacks. A single participant listener does then
receive both, verified with a mismatched reader and writer in the same participant:

```cpp
participant.set_listener(
    listener,
    dds::core::status::StatusMask::requested_incompatible_qos()
        | dds::core::status::StatusMask::offered_incompatible_qos());
// combined mask = 00000000000000000000000001100000  (bits 5 and 6)
```

This app's listener class implements both callbacks, but the app deliberately does **not**
combine the masks — it installs them on separate participants, so the output shows which side
raises which: the subscriber participant gets `requested_incompatible_qos()`, the publisher
participant gets `offered_incompatible_qos()`.

## Which listener wins

"Most local listener whose mask enables the status" is easy to state and easy to get
backwards. Measured, with a reliable reader against a best-effort writer:

| Participant listener mask | DataReader listener mask | Which fired |
| --- | --- | --- |
| `requested` | *(no reader listener)* | participant |
| `requested` | `requested` | **reader** |
| `requested` | `offered` | **participant** |
| *(none)* | `requested` | reader |
| *(none)* | `offered` | nothing |

Two things to take from this:

- Installing a participant listener does **not** steal the status from a DataReader listener
  that has it enabled. The reader still wins (row 2).
- If a reader listener appears to "stop firing" when you add a participant listener, check
  the *reader's own mask* first (row 3). A reader whose mask does not cover the status never
  had it enabled, so it propagates up — the participant listener did not take it away.

## Polling instead of listening

There is no participant-level equivalent to `DataReader::requested_incompatible_qos_status()`,
and that is by design: it is not a participant status, and there is no aggregated
participant-wide status object. To poll, enumerate the endpoints and poll each:

```cpp
std::vector<dds::sub::Subscriber> subscribers;
rti::sub::find_subscribers(participant, std::back_inserter(subscribers));
for (auto& subscriber : subscribers) {
    std::vector<dds::sub::AnyDataReader> readers;
    rti::sub::find_datareaders(subscriber, std::back_inserter(readers));
    for (auto& any_reader : readers) {
        auto status = any_reader.get<MyType>().requested_incompatible_qos_status();
    }
}
```

`rti::pub::find_publishers` / `rti::pub::find_datawriters` with
`offered_incompatible_qos_status()` cover the writer side. Enumeration finds the *implicit*
publisher and subscriber too, so this works even if you never created one explicitly.

**That loop only works if every reader is the same type.** `dds::sub::AnyDataReader` exposes
`qos()`, `topic_name()`, `type_name()`, `subscriber()` and `get<T>()` — but **no status
accessor**, so the status can only be reached by retyping. And `get<T>()` *throws*
`dds::core::InvalidDowncastError` on a reader of a different type rather than returning null,
so one hardcoded type across a mixed participant fails on the first foreign reader.

For a genuinely type-agnostic sweep, go through the untyped handle. `AnyDataReader::operator->()`
yields an `rti::sub::UntypedDataReader`, whose `native_reader()` needs no type parameter, and
the C status call is untyped:

```cpp
DDS_RequestedIncompatibleQosStatus status =
    DDS_RequestedIncompatibleQosStatus_INITIALIZER;
DDS_DataReader_get_requested_incompatible_qos_status(
    any_reader->native_reader(), &status);
// status.total_count, status.total_count_change, status.last_policy_id
```

Measured over one participant holding a `Position` reader and a `Command` reader, both
mismatched:

| Approach | `Position` reader | `Command` reader |
| --- | --- | --- |
| `get<Position>()` on every reader | `total_count=1` | **throws `InvalidDowncastError`** |
| `->native_reader()` + C API | `total_count=1` | `total_count=1`, `last_policy_id=11` |

Use the typed form when the participant is single-type or you can dispatch on `type_name()`;
use the untyped form for a general participant-wide sweep. Note the C struct exposes
`policies` as a `DDS_QosPolicyCountSeq`, which needs the C sequence accessors rather than
range-based iteration.

**Reading a status consumes its delta.** `total_count` keeps accumulating, but
`total_count_change` counts only what happened since the status was last read — and a
listener callback counts as a read. Measured on the same mismatch:

| | first read | second read |
| --- | --- | --- |
| polling only | `total_count=1  total_count_change=1` | `total_count=1  total_count_change=0` |
| listener installed | `total_count=1  total_count_change=0` | `total_count=1  total_count_change=0` |

So a listener and a poller on the same entity steal each other's deltas, as do two pollers.
Use `total_count` for anything durable.

## How the app is built

```cpp
class QosMismatchParticipantListener
        : public dds::domain::NoOpDomainParticipantListener {
public:
    void on_requested_incompatible_qos(
        dds::sub::AnyDataReader& reader,
        const dds::core::status::RequestedIncompatibleQosStatus& status) override
    { ... }
};

auto listener = std::make_shared<QosMismatchParticipantListener>();

participant.set_listener(
    listener,
    dds::core::status::StatusMask::requested_incompatible_qos());
```

`NoOpDomainParticipantListener` is the convenient base class: it supplies empty bodies for
every callback, so only the ones you care about need overriding.

**Listener lifetime**: `set_listener()` takes a `std::shared_ptr<Listener>` and the
participant holds that reference, so the listener stays alive on its own. The older
`participant.listener(Listener*, mask)` form is deprecated precisely because it required you
to manage the raw pointer's lifetime by hand. The app also calls `set_listener(nullptr)` at
the end — that is *not* required for teardown (destroying the participant releases the
listener, and this listener holds no entity reference that could form a cycle); it just stops
callbacks deterministically so nothing prints after the result line.

**Entity lifetime**: the participants, reader and writer are declared as plain values, not
smart pointers. DDS entities in the Modern C++ API are reference types (`dds::core::Reference`)
that already carry shared ownership, so wrapping them in a `unique_ptr`/`shared_ptr` adds a
second, redundant ownership layer — see RTI's
[Don't Declare Entities As Pointers](https://community.rti.com/best-practices/modern-c-api-don%E2%80%99t-declare-entities-pointers).
Because this app creates them conditionally based on `--mode`, they are initialized to
`dds::core::null` and assigned later, and tested with `!= dds::core::null`:

```cpp
dds::domain::DomainParticipant sub_participant = dds::core::null;
...
sub_participant = dds::domain::DomainParticipant(args.domain_id, participant_qos);
```

For the same reason the local `dds::sub::Subscriber` / `dds::pub::Publisher` handles are
allowed to go out of scope while the reader and writer they created stay alive — the child
entity keeps its parent alive.

By default the app runs both sides in one process, using two participants (a subscriber
participant that owns the listener and a publisher participant that owns the mismatched
writer), so a single command reproduces the callback end to end.

## Status object API notes

Verified against the **Connext 7.3.1** Modern C++ headers. Every member is a method:

| Member | Type |
| --- | --- |
| `status.total_count()` | `int32_t` |
| `status.total_count_change()` | `int32_t` |
| `status.last_policy_id()` | `dds::core::policy::QosPolicyId` |
| `status.policies()` | `dds::core::policy::QosPolicyCountSeq`, each element with `.policy_id()` and `.count()` |

`QosPolicyId` is a plain `uint32_t` (`typedef uint32_t QosPolicyId` in
`dds/core/types.hpp`), so it prints as a bare number. To get a readable name, the app maps it
back through the policy traits:

```cpp
if (dds::core::policy::policy_id<Policy>::value == id) {
    name = dds::core::policy::policy_name<Policy>::name();
}
```

> **Note for anyone porting between the two languages:** the member names differ. C++ uses
> `last_policy_id()` and `QosPolicyCount::policy_id()`; the Python binding uses
> `last_policy` and `QosPolicyCount.policy`. Python also exposes
> `RequestedIncompatibleQosStatus.total_count` as a bound method while the Offered variant is
> a property — the C++ API is consistent and has no such quirk.

Also worth knowing: an exception escaping a listener callback is swallowed by the middleware.
It surfaces only as an `ASSERT REMOTE DW ... LC:Discovery` error line in the Connext log, and
the rest of the callback body never runs — which looks exactly like the callback not firing
at all. Keep callback bodies defensive.

## Command-line options

| Option | Default | Description |
| --- | --- | --- |
| `-d`, `--domain` | `1` | Domain ID |
| `-q`, `--qos-file` | `dds/qos/DDS_QOS_PROFILES.xml` | QoS profiles XML (`run.sh` passes an absolute path) |
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

## Building

Built as part of the top-level project:

```bash
source $NDDSHOME/resource/scripts/rtisetenv_<arch>.bash
mkdir -p build && cd build
cmake .. -DCONNEXTDDS_ARCH=<arch>
cmake --build .
```

Or build just this app:

```bash
cmake --build . --target incompatible_qos_listener
```

`run.sh` builds the whole project if the binary is missing.

## Running

Single process, both sides:

```bash
./run.sh --domain 1
./run.sh --domain 1 --policy durability
```

Two processes — start the publisher first, then the subscriber in another terminal:

```bash
./run.sh --domain 1 --mode publisher       # terminal 1
./run.sh --domain 1 --mode subscriber      # terminal 2
```

In `--mode publisher` the same listener is installed on the publishing participant with
`offered_incompatible_qos()`, demonstrating the writer-side counterpart also arriving at the
participant level.

The subscriber also matches the Python publisher, and vice versa:

```bash
../../python/incompatible_qos_listener/run.sh --domain_id 1 --mode publisher
./run.sh --domain 1 --mode subscriber
```

## Expected output

```
[SUBSCRIBER] Reader created on topic 'Position'
[PUBLISHER] Writer created on topic 'Position'
[MAIN] Forcing a 'reliability' QoS mismatch on domain 1
[MAIN] Waiting up to 10s for the participant callback...
[PARTICIPANT_LISTENER] on_requested_incompatible_qos
  Reader topic: Position
  Total count: 1
  Total count change: 1
  Last policy: Reliability (id 11)
  Policy Reliability: 1 mismatch(es)
[RESULT] PASS - on_requested_incompatible_qos fired 1 time(s) at the participant level.
```

## Troubleshooting

**No callback fires.** In order of how often it turns out to be the cause:

1. **Wrong status for the side you are on.** A participant holding DataReaders raises
   `REQUESTED_INCOMPATIBLE_QOS`, never `OFFERED_INCOMPATIBLE_QOS` — the offered status is
   raised in the *remote* writer's participant. Masking `offered_incompatible_qos()` on a
   reader-side participant enables a bit that is never set, and fails silently. See
   [Which status, and on which side](#which-status-and-on-which-side).
2. **Wrong override signature.** See the next entry — it also fails silently.
3. **A more local listener is consuming it.** Check that the `DataReader` and its
   `Subscriber` have no listener covering the status.
4. Both sides really are on the same domain and topic.

**The override never gets called and the compiler was happy.** Check the parameter type: the
participant-level override takes `dds::sub::AnyDataReader&`, not `dds::sub::DataReader<T>&`.
Keeping `override` on the declaration turns that mistake into a compile error.

For general build and license setup, see [../README.md](../README.md).
