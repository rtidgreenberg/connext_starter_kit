# RTI Spy

`rti_spy` is a Python/Textual DDS monitoring tool for RTI Connext DDS. It
discovers participants, readers, and writers through builtin topics and can
subscribe to discovered writer topics using DynamicData.

## Quick Start

From the repository root:

```bash
./tools/rti_spy/run_rtispy.sh
```

If `--domain` is omitted and the launcher is running in an interactive terminal,
`rti_spy` first asks you to either type a DDS domain ID directly, or press
Enter to listen for active DDS domains (up to 32s, see "Active Domain
Scanning" below). If you choose to listen, it then prompts for a domain,
defaulting to the lowest domain ID it found; press Enter to accept the
default. In non-interactive runs it falls back to domain `1` without prompting.

## Operator Manual

### Explore a DDS Domain

Start Spy and choose a domain, either by entering its ID or by letting the tool
listen for active-domain announcements. The first screen lists discovered
participants and their host addresses. Select a participant and press `Enter`
to inspect its readers and writers.

Select an endpoint and press `Enter` to open its detail view. For a writer, Spy
uses the discovered DynamicType and matching reader-side QoS to subscribe and
render incoming DynamicData samples. It creates no generated type support and
closes the temporary reader when you leave the detail screen. Reader endpoints
remain inspectable, but cannot be subscribed to because they do not publish
samples.

### Inspect Distributed Logger Data

Highlight a participant and press `l` to open its Distributed Logger dialog.
When that participant exposes the required `rti/distlog` topics, the dialog
shows its log messages and state and allows selecting a filter level. This sends
an administration request to the selected participant, so use it only when you
intend to modify that logger's filter threshold.

### Refresh and Exit

Discovery listeners update the participant and endpoint inventory while Spy is
running. Use the Textual navigation keys to move through tables, `b` or `Esc` to
return from a detail view, and `q` to close the tool. Provide `--debug-log` when
you need a persistent discovery/subscription trace for troubleshooting.

## What the Launcher Does

`run_rtispy.sh` auto-detects the Connext version from `NDDSHOME` and picks a
matching, isolated Python environment and `rti.connext` version:

| NDDSHOME version | Python  | venv                    | rti.connext |
|-------------------|---------|-------------------------|-------------|
| 7.3.x              | 3.9     | `connext_dds_env_7.3/`  | 7.3.1       |
| 7.7.x (default)    | newest installed 3.10-3.14 | `connext_dds_env/` for 3.10; `connext_dds_env_7.7_py<XY>/` otherwise | 7.7.0 |

It will:

- detect `NDDSHOME` (or use `$NDDSHOME` if already set/exported)
- detect the Connext version and select the matching Python/venv/`rti.connext` above; when a bundled activated wheel is available, prefer the newest installed Python with a matching wheel
- detect `RTI_LICENSE_FILE`
- create or rebuild the matching versioned virtual environment if needed
- install the matching `rti.connext` version, then the rest of `tools/rti_spy/requirements.txt`
- start `rtispy.py`

Switching between a Connext 7.3.x and 7.7.x install (via `NDDSHOME`) reuses each
version's own venv, so no rebuild/reinstall is needed when switching back and forth.

## Installing the RTI Connext Python API

You don't need to install `rti.connext` yourself — `run_rtispy.sh` does it for
you automatically, and prefers a local install over a PyPI download:

1. **Bundled, pre-activated wheel (preferred).** Every native Connext install
   ships a pre-activated Python wheel (no separate `RTI_LICENSE_FILE` needed
   for the wheel itself) under
   `$NDDSHOME/resource/python_api/rti_connext_activated-<version>-cp<XY>-*.whl`.
   If a wheel matching the detected Connext version and target Python version
   is found there, the launcher installs it directly from disk — no network
   access required.
2. **PyPI fallback.** If no matching bundled wheel is found (e.g. `NDDSHOME`
   isn't set, or it's a nonstandard/custom build), the launcher installs the
   public `rti.connext==<version>` package from PyPI instead.

Both packages provide the same `rti.connextdds` module, so this is transparent
to the app. To use it:

```bash
export NDDSHOME=/path/to/your/rti_connext_dds-X.Y.Z
./tools/rti_spy/run_rtispy.sh
```

That's it — the launcher detects the version from `NDDSHOME`, picks the
matching Python/venv (table above), installs the bundled wheel if present, and
starts `rtispy.py`. Re-running is fast: once the correct version is installed,
the launcher skips reinstalling on subsequent runs.

## Requirements

- RTI Connext DDS 7.3.x or 7.7.x available locally
- Python 3.10 available as `python3.10` (for 7.7.x), and/or Python 3.9 available
  as `python3.9` (for 7.3.x). If missing, the launcher prints the exact
  `sudo apt install python3.9 python3.9-venv` command needed and stops.
- A valid RTI license file

`tools/rti_spy/requirements.txt` no longer pins `rti.connext`; the version is
selected automatically to match `NDDSHOME`. The Textual UI dependencies are
still listed there.

For command-line options, direct invocation, and startup troubleshooting, see
[CLI_REFERENCE.md](CLI_REFERENCE.md).

## Active Domain Scanning

When no `--domain` is given interactively, `rti_spy` first asks whether to
type a domain ID directly or listen for active domains. If you choose to
listen (press Enter at that prompt), it passively listens for RTI Connext's
"default domain announcement" traffic (RTPX-magic packets sent by every
participant to domain 0's default discovery multicast address/port,
`239.255.0.1:7400`) to discover which domain IDs currently have active
participants, then offers the lowest one found as the next prompt's default.

This is best-effort:

- It relies on the default UDPv4 multicast discovery address/port mapping;
  participants using custom multicast addresses, custom port mappings, or
  with UDPv4 discovery disabled won't be seen.
- A remote participant only sends this announcement when created and then
  every `default_domain_announcement_period` (30s by default) afterward -
  there's no catch-up resend for a listener that starts later. Because our
  scan starts at an arbitrary point in that cycle, it defaults to just over
  30s (`--scan-timeout 32.0`) so already-running domains are reliably caught.
- Cross-domain announcements are only visible through the participant
  built-in reader (`participant.participant_reader`), not through
  `discovered_participants()`/`discovered_participant_data()`, which only
  reflect normal same-domain SPDP matching.

Use `--scan-timeout` to shorten/lengthen the wait, or `--no-domain-scan` to
skip straight to the domain prompt (still defaults to `1`).

## Deploying RTI Spy as a PyInstaller Bundle

The normal launcher remains the easiest way to run `rti_spy` on a development
machine. Use these steps to create a compressed PyInstaller folder bundle for a
compatible Linux target.

1. Install the build prerequisites. For a Connext 7.3 `cp39` RTI Python wheel
  on Debian/Ubuntu:

  ```bash
  sudo apt install python3.9 python3.9-venv libpython3.9
  ```

  Package names vary by distribution.

2. Locate the RTI Python wheel. Wheels installed with Connext are commonly
  under `$NDDSHOME/resource/python_api/`, for example:

  ```text
  $NDDSHOME/resource/python_api/rti_connext_activated-7.3.1-cp39-*.whl
  ```

3. Prepare the connected build environment. This one-time step needs network
  access to install PyInstaller and non-RTI Python dependencies:

  ```bash
  ./scripts/prepare_rti_spy_bundle_env.sh \
    --wheel "$NDDSHOME"/resource/python_api/rti_connext_activated-7.3.1-cp39-*.whl
  ```

4. Create the deployment package. This reuses the RTI Python wheel recorded
  during preparation and does not download Python packages:

  ```bash
  ./scripts/build_rti_spy_bundle.sh
  ```

  The `.tar.gz` artifact is written to `build/rti_spy_bundle/` and includes
  the Connext version, Python ABI, and build architecture in its filename. To
  use a different wheel, rerun the preparation step with that wheel.

5. Copy the `.tar.gz` to the target, extract it, and run it:

  ```bash
  tar -xzf rti_spy-*.tar.gz
  ./rti_spy/rti_spy --theme textual-light
  ```

  The target does not need Python, pip, the source repository, or the RTI
  Python wheel. When built from an activated RTI Python wheel, the bundle also
  does not need a separate runtime license installation on the target. It
  still needs a compatible Linux architecture, glibc baseline, and DDS network
  access.

## Testing

Run the startup tests:

```bash
PYTHONPATH=tools/rti_spy ./connext_dds_env/bin/python -m unittest tools/rti_spy/test/test_startup_live.py
```

Run the discovery/subscription integration test:

```bash
PYTHONPATH=tools/rti_spy ./connext_dds_env/bin/python -m unittest tools/rti_spy/test/test_live_e2e_integration.py
```
