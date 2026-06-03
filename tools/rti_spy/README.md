# RTI Spy

RTI Spy is a Python/Textual DDS monitoring tool for RTI Connext DDS applications.
It uses builtin topics to discover participants, DataReaders, and DataWriters on a
specified domain, then can subscribe to writer topics using DynamicData and matched QoS.

## Files

- `rtispy.py` — application source
- `run_rtispy.sh` — environment/bootstrap runner
- `install.sh` — RTI Spy dependency installer
- `requirements.txt` — RTI Spy Python package requirements

## Usage

From the repository root:

```bash
./tools/rti_spy/run_rtispy.sh --domain 1
```

Options:

- `--domain` / `-d` — DDS domain ID, default `1`
- `--interval` / `-i` — refresh interval in seconds, default `10`

The runner:

1. Detects `NDDSHOME` when it is not set.
2. Validates `RTI_LICENSE_FILE` or `$NDDSHOME/rti_license.dat`.
3. Uses the shared repository virtual environment at `connext_dds_env/`.
4. Runs `tools/rti_spy/install.sh` if required dependencies are missing.
5. Starts `rtispy.py` with the provided arguments.

Manual setup:

```bash
./tools/rti_spy/install.sh
```

## DDS Patterns Used

- Builtin topic discovery via DCPSParticipant, DCPSPublication, and DCPSSubscription.
- Runtime DynamicType capture from discovered endpoint data.
- DynamicData topic and reader creation without generated code.
- QoS matching from discovered writer QoS.
- Optional Distributed Logger monitoring and command request/reply flows.
