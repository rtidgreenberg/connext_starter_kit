# Distributed Logger Ordering Test

Investigation into how DDS instance keying and Presentation QoS affect message
ordering when using RTI Distributed Logger.

## Key Findings

### 1. `level` Is a Key Field — Each Log Level Is a Separate DDS Instance

The Distributed Logger `LogMessage` type (defined in
`$NDDSHOME/resource/idl/distlog.idl`) has **three `@key` fields**:

```idl
struct LogMessage {
    HostAndAppId hostAndAppId;  // contains two @key members:
                                //   rtps_host_id  @key
                                //   rtps_app_id   @key
    long level;                 // @key ← this one
    string<256> category;
    string<8192> message;
    MessageId messageId;
};
```

This means **each log level (FATAL, ERROR, WARNING, NOTICE, INFO, …) is a
separate DDS instance**. A publisher writing round-robin across levels is
writing to 5 different instances.

### 2. Presentation QoS Is Hard-Coded to INSTANCE Scope

Distributed Logger sets its internal Publisher Presentation QoS to:

| Parameter        | Value      |
|------------------|------------|
| `access_scope`   | `INSTANCE` |
| `ordered_access`  | `false`    |
| `coherent_access` | `false`    |

This is hard-coded inside the library and **cannot be overridden** via
`LoggerOptions.qos_library` / `qos_profile`. To get cross-instance ordered
access (`TOPIC` or `GROUP` scope), you would need to bypass Distributed Logger
and write your own DataWriter.

### 3. `take()` / `take_async()` Returns Instance-Grouped Samples

Per the DDS specification, when `access_scope = INSTANCE`:

> Samples accessed via `read()` / `take()` are ordered **per-instance** but the
> ordering **across instances** is implementation-defined.

In practice, RTI Connext's Python API groups all samples from instance A, then
all from instance B, etc. If the publisher sent:

```
FATAL[0] → ERROR[1] → WARNING[2] → NOTICE[3] → INFO[4] → FATAL[5] → ERROR[6] → ...
```

The subscriber's `take()` or `take_async()` returns:

```
FATAL[0], FATAL[5], FATAL[10], ...   (all FATAL first)
ERROR[1], ERROR[6], ERROR[11], ...   (then all ERROR)
WARNING[2], WARNING[7], WARNING[12], ...
...
```

This is **not a bug** — it's the specified behavior for `INSTANCE` access scope.

### 4. rtiddsspy Shows True Arrival Order

`rtiddsspy` uses the C API's `take_next_sample()`, which walks the data cache
**sample-by-sample in arrival order** rather than instance-by-instance. This is
why rtiddsspy shows perfectly ordered output (seq 0, 1, 2, 3, …) while the
Python subscriber shows instance-grouped output.

### 5. Workaround: Sort by Timestamp After `take()`

The Python API does **not** expose `take_next_sample()`. The available
workaround is to call `take()` then sort the returned collection by
`source_timestamp` (set by the writer) or `reception_timestamp` (set by the
reader) before processing:

```python
samples = reader.take()
samples.sort(key=lambda s: s.info.source_timestamp)
for sample in samples:
    process(sample.data, sample.info)
```

This reconstructs the original send order across instances.

## Test Components

### publisher.py

Sends log messages via `distlog.Logger` in configurable patterns:

| Pattern            | Description                                 |
|--------------------|---------------------------------------------|
| `round-robin`      | Cycle all 5 levels each round               |
| `burst-per-level`  | N messages at one level, then next           |
| `reverse`          | Lowest to highest severity (INFO → FATAL)   |
| `interleaved`      | Alternating level pairs                      |
| `same-level`       | All WARNING (single-instance baseline)       |
| `all`              | Run all patterns sequentially                |

Each message embeds a global `[seq=N]` counter in the message body for order
tracking.

### subscriber.py

Discovers the distlog writer via the `DCPSPublication` builtin topic (same
approach as `rtispy.py`), then reads messages in one of three modes:

| Mode     | Method                                | Ordering Behavior         |
|----------|---------------------------------------|---------------------------|
| `bulk`   | `take_async()` (default)              | Instance-grouped          |
| `single` | Polling `take()` in a loop            | Instance-grouped          |
| `sorted` | `take()` + sort by `source_timestamp` | Reconstructed send order  |

Output includes per-message order analysis (`OK` / `**OOO**`) and a summary
showing total out-of-order count, order breaks, and any gaps or duplicates.

## Running the Tests

Activate the virtual environment first:

```bash
source connext_dds_env/bin/activate
```

### Test 1: Python bulk mode (instance-grouped ordering)

Terminal 1 — start subscriber:
```bash
python subscriber.py -d 0 -m bulk
```

Terminal 2 — run publisher:
```bash
python publisher.py -d 0 -p round-robin -n 5
```

Press `Ctrl+C` in terminal 1 after messages appear to see the order analysis
summary. Expect **OOO** markers at instance boundaries (all FATAL first, then
ERROR, etc.).

### Test 2: Python sorted mode (reconstructed send order)

Terminal 1:
```bash
python subscriber.py -d 0 -m sorted
```

Terminal 2:
```bash
python publisher.py -d 0 -p round-robin -n 5
```

Press `Ctrl+C` in terminal 1. Expect **0 out-of-order** — `source_timestamp`
sorting reconstructs the original send order.

### Test 3: rtiddsspy (arrival order baseline)

Terminal 1:
```bash
rtiddsspy -domainId 0 -printSample
```

Terminal 2:
```bash
python publisher.py -d 0 -p round-robin -n 5
```

Press `Ctrl+C` in terminal 1. Expect **perfectly ordered** seq numbers
(0, 1, 2, 3, …) because rtiddsspy uses the C API's `take_next_sample()`.

### Test 4: Single-instance baseline

Terminal 1:
```bash
python subscriber.py -d 0 -m bulk
```

Terminal 2:
```bash
python publisher.py -d 0 -p same-level -n 5
```

Press `Ctrl+C` in terminal 1. Expect **0 out-of-order** — all messages go to
the same instance (WARNING), so INSTANCE scope ordering is sufficient.

## Expected Results

| Reader              | Out-of-Order (round-robin, multi-level) | Out-of-Order (same-level) |
|---------------------|-----------------------------------------|---------------------------|
| Python bulk mode    | Many (at every instance boundary)       | 0                         |
| Python sorted mode  | 0                                       | 0                         |
| rtiddsspy           | 0                                       | 0                         |

## Implications

- If your application processes log messages from Distributed Logger and **order
  matters across severity levels**, you must sort after `take()`.
- If you only care about ordering **within a single level**, the default
  `INSTANCE` scope already guarantees that.
- If you need true cross-instance ordered access from the DDS layer itself, you
  would need `access_scope = TOPIC` and `ordered_access = true` on the
  Publisher **and** Subscriber — which requires bypassing Distributed Logger's
  hard-coded QoS.
