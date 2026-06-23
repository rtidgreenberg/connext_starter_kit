# RS GUI v2 Troubleshooting

This guide covers common startup issues detected by `run_rs_gui.sh` diagnostics.

## Run Diagnostics Only

```bash
cd services/rs_gui
./run_rs_gui.sh --diagnostics-only --gui
```

## Common Issues

### NDDSHOME not detected

Set `NDDSHOME` or install RTI Connext in a discoverable location:

```bash
export NDDSHOME=/path/to/rti_connext_dds-<version>
```

### RTI license not found

Set `RTI_LICENSE_FILE` or place `rti_license.dat` in one of these locations:

- `NDDSHOME/rti_license.dat`
- `~/.rti/rti_license.dat`
- `~/rti_license.dat`

### XML type files are missing or stale

Regenerate rs_gui-owned XML types:

```bash
cd services/rs_gui
./setup.sh
```

If you changed RTI installations, rerun `./setup.sh` to refresh
`xml_types/.generated_from_nddshome` metadata.

### RTI service executable missing

Diagnostics checks for:

- `rtirecordingservice`
- `rtireplayservice`
- `rticonverter`

Expected location is `NDDSHOME/bin/`. Install a full RTI Connext host package if
binaries are missing.

### Replay launch fails with `No valid metadata file found in directory`

Replay Service needs a valid recording directory containing at least
`metadata.db` and `data_0.db`.

Checks:

- Confirm the selected replay input directory is a real recording output
- Prefer an absolute path when launching Replay from the GUI
- If using a relative path, resolve it from `services/rs_gui/`

### Replay admin readiness times out

If Replay starts but GUI close cleanup reports a timeout waiting for Service
Admin endpoints, check these first:

- `<administration>` is enabled in `dds/qos/replay_service.xml`
- The admin domain id used by the launch matches `REPLAY_ADMIN_DOMAIN_ID`
- The process stayed alive long enough to create the admin endpoints

If the process exits early, fix that startup failure first. GUI close cleanup
can fall back to local termination, but that should be treated as degraded
behavior rather than a substitute for a healthy admin path.

### Replay monitoring evidence does not appear

Replay monitoring depends on a healthy service instance plus the configured
monitoring domain.

Checks:

- `<monitoring>` is enabled in `dds/qos/replay_service.xml`
- The monitoring domain id used by the launch matches `REPLAY_MON_DOMAIN_ID`
- The replay input directory contains data for the selected session/topics

Expected monitoring identities are rooted under `/replay_services/<config>` and
extend to session/topic resources, for example:

- `/replay_services/xcdr`
- `/replay_services/xcdr/sessions/DefaultSession`
- `/replay_services/xcdr/sessions/DefaultSession/topics/DefaultTopicGroup@Square`

### Replay or Recording process exits unexpectedly

Per-process logs are written under `services/rs_gui/service_logs/`.

Useful checks:

- Inspect the newest `rtireplayservice_*.log` or `rtirecordingservice_*.log`
- Re-run the explicit live gates with `--output` pointing into `test_output/`
- Compare the reported config paths, domain ids, and database path with the
	service XML variables

## Bypass Diagnostics Temporarily

Use this only for short-term local debugging:

```bash
./run_rs_gui.sh --skip-diagnostics --gui
```
