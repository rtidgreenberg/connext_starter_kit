# Distributed Logger Publisher (Python)

A standalone Python application that publishes periodic RTI Distributed Logger
messages over DDS. It uses the standard `rti.logging.distlog` API, so the
messages can be viewed by Admin Console, `rti_spy`, or another compatible DDS
subscriber.

## Run

```bash
./run.sh --domain-id 1
```

Publish five warning messages immediately:

```bash
./run.sh --domain-id 1 --level warning --count 5 --interval 0
```

## Options

```text
-d, --domain-id ID       DDS domain ID (default: 1)
-i, --interval SECONDS   Seconds between messages (default: 1.0)
-c, --count COUNT        Number of messages; 0 runs until interrupted
--category NAME          Distributed logger category
--application-kind NAME  Application kind embedded in log records
--level LEVEL            debug, info, warning, or error (default: info)
```

The launcher provisions the repository Python environment and validates the
RTI license configuration before starting the publisher.