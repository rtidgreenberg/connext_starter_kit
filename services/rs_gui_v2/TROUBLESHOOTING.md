# RS GUI v2 Troubleshooting

This guide covers common startup issues detected by `run_gui.sh` diagnostics.

## Run Diagnostics Only

```bash
cd services/rs_gui_v2
./run_gui.sh --diagnostics-only --gui
```

## Common Issues

### Cannot import dearpygui.dearpygui

Install dependencies in the repository virtual environment:

```bash
../../connext_dds_env/bin/python -m pip install -r requirements.txt
```

The requirements file pins the Dear PyGui version used by this workspace. If an
unpinned install pulls a newer wheel and fails with a `GLIBCXX_* not found`
error, reinstall from `requirements.txt`.

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

Regenerate rs_gui_v2-owned XML types:

```bash
cd services/rs_gui_v2
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

## Bypass Diagnostics Temporarily

Use this only for short-term local debugging:

```bash
./run_gui.sh --skip-diagnostics --gui
```
