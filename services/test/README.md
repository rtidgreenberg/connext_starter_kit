# Services — End-to-End Tests

Automated end-to-end tests for the services start scripts (`start_record.sh`,
`start_convert.sh`, `start_replay.sh`).

> **Tip:** GUI-specific tests (unit, widget, integration, E2E tags) live in
> [`rs_gui/test/`](../rs_gui/test/README.md).

## Running Tests

```bash
cd services

# Run all services tests (7 tests)
python3 test/run_all_tests.py -v

# Run standalone
python3 test/test_e2e_services.py -v
```

## Test Files

| File | What it tests | Tests |
|------|--------------|-------|
| `test_e2e_services.py` | `start_record.sh`, `start_convert.sh`, `start_replay.sh` | Full E2E pipeline + orphan process cleanup |
| `run_all_tests.py` | — | Suite runner — discovers and runs all `test_*.py` files |

## Prerequisites

- `$NDDSHOME` set (auto-detected from `~/rti_connext_dds-*` if not set)
- `rtirecordingservice`, `rtireplayservice`, `rticonverter` binaries available
- `rti.connext` Python package from PyPI (`== 7.7.0`)
- Centralized QoS profiles at `dds/qos/DDS_QOS_PROFILES.xml`

Tests are automatically skipped when prerequisites are unavailable.

## Test Pipeline (`test_e2e_services.py`)

The test exercises the complete Record → Convert → Replay workflow:

1. **Clean** — removes any previous `log_dir/` and `converted/` directories
2. **Record** — starts Recording Service via `start_record.sh deploy`
3. **Publish** — writes 20 DDS `Command` samples on domain 1 (waits for
   discovery before publishing to avoid race conditions)
4. **Verify recording** — stops the recorder via SIGTERM, verifies XCDR
   database files (`.dat`, `metadata.db`) exist and contain data
5. **Convert to CSV** — runs `start_convert.sh csv`, verifies exit code
6. **Validate CSV** — checks for `Command` topic CSV file, verifies header
   columns and data row count
7. **Replay** — runs `start_replay.sh` to replay the recorded data
8. **Cleanup** — removes test output directories
9. **Orphan check** — verifies no RTI service processes remain running
   (SIGTERM → SIGKILL escalation if needed)
