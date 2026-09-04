# rs_gui

`rs_gui` is the desktop operator interface for RTI Recording and Replay
Services in this repository. It provides a Tk-based workspace for launching,
monitoring, and controlling services without manually coordinating terminal
processes and Service Admin commands.

## Start the GUI

From the repository root:

```bash
./services/rs_gui/run_rs_gui.sh
```

The launcher prepares the repository Python environment, checks the RTI
installation and license, and opens the live Record/Replay workspace.

## Operator Manual

### Recording

Use the **Recording** tab to create and supervise Recording Service jobs.

- Select an existing discovered service to inspect its state, owner, host,
	process ID, uptime, readiness, and recent output.
- Configure a new recording with the data, admin, and monitoring domains; a
	Recording Service configuration; storage location; topic filters; and
	verbosity, then launch it from the tab.
- Pause or resume a running recording when you need to retain the same service
	instance but temporarily stop capture. Stop ends capture; shutdown requests a
	graceful service exit; terminate is reserved for a GUI-owned process that no
	longer responds.
- Add tags while recording to mark events or time windows for later playback.
	The tab presents the tags observed by Recording Service and the selected
	recording's current storage file and size when monitoring provides them.

### Replay

Use the **Replay** tab to play a Recording Service database back into DDS.

- Choose a recording directory or one of its data database files. The GUI
	normalizes a selected database file to its recording directory.
- Set the Replay configuration, domains, and playback controls, then launch the
	service. The status panel shows readiness, replay state, progress, selected
	database, and service monitoring details.
- Start, pause, resume, or stop playback according to the selected service's
	current state. A stopped GUI-owned replay service is relaunched when started
	again. Use shutdown to request a graceful exit, or terminate only for a local
	process that needs escalation.
- List recorded tags and select a tag window to focus playback on the associated
	time interval.

### Debug

Use the **Debug** tab to inspect the application event log and service command
activity while operating the workspace. This is the first place to look when a
launch, readiness check, or lifecycle command has an unexpected result.

### Recorded QoS Analysis Prototype

Replay also offers a read-only **Analyze QoS** action when the selected
recording directory contains a sibling `discovery.db`. It reconstructs recorded
participant and endpoint lifetimes, compares overlapping writers and readers on
the same domain and topic, and lists QoS mismatches, type mismatches, and values
that could not be evaluated from the recording.

This is a coarse reference prototype, not an authoritative DDS matching
history. It does not cover all lifecycle, type-compatibility, security,
transport, data-representation, or related edge cases. Supported QoS mismatch
analysis is planned for an upcoming Connext Studio release.

## Requirements

- Python 3.11 available locally
- RTI Connext DDS 7.7.x available through `NDDSHOME`
- Tkinter available in that Python installation
- A valid RTI license file

## DDS XML Setup

Refresh generated XML type artifacts after switching `NDDSHOME` to another
Connext installation:

```bash
cd services/rs_gui
./setup.sh
```

## Testing

Run the main suite from `services/rs_gui`:

```bash
export VENV_PYTHON=$(ls -d ../../connext_dds_env_*py311/bin/python | head -1)
"$VENV_PYTHON" test/run_all_tests.py -v
```

See [CLI_REFERENCE.md](CLI_REFERENCE.md) for launcher switches, mock and
headless checks, and direct application entrypoints. For environment and startup
issues, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
