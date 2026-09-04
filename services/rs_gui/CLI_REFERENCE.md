# rs_gui Command-Line Reference

The standard operator command is:

```bash
./services/rs_gui/run_rs_gui.sh
```

It starts the live Tk Record/Replay workspace. No GUI mode flag is required.

## Launcher Switches

Use these options with `run_rs_gui.sh` when preparing an environment or
troubleshooting startup:

| Switch | Purpose |
| --- | --- |
| `--prepare-dds` | Run `setup.sh` before launch and require Connext-specific diagnostics. |
| `--diagnostics-only` | Run startup diagnostics and exit without opening the GUI. |
| `--skip-diagnostics` | Bypass startup diagnostics for this launch. |
| `--debug` | Enable debug logging explicitly. This is the default. |
| `--no-debug` | Disable debug logging for this launch. |

## Development and Check Modes

These app options are intended for tests and development, not normal operation:

| Option | Purpose |
| --- | --- |
| `--mock-gui` | Open the Tk workspace with explicit mock/demo data. |
| `--mock-gui-check` | Build the session-backed mock workspace and exit. |
| `--headless-check` | Start and stop the app core without GUI or DDS entities. |

For example:

```bash
./services/rs_gui/run_rs_gui.sh --diagnostics-only
./services/rs_gui/run_rs_gui.sh --prepare-dds
./services/rs_gui/run_rs_gui.sh --mock-gui
```

## Direct App Entrypoint

The launcher should be preferred because it resolves the repository Python
environment, RTI installation, license, and dependencies. When that environment
is already active, the direct entrypoint accepts the same development/check
options:

```bash
./connext_dds_env_7.7_py311/bin/python services/rs_gui/rs_gui_app.py --headless-check
```

The direct entrypoint also retains `--tk-gui` and `--tk-gui-check` for minimal
Tk-scaffold compatibility checks.