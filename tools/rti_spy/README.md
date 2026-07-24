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

## What the Launcher Does

`run_rtispy.sh` auto-detects the Connext version from `NDDSHOME` and picks a
matching, isolated Python environment and `rti.connext` version:

| NDDSHOME version | Python  | venv                    | rti.connext |
|-------------------|---------|-------------------------|-------------|
| 7.3.x              | 3.9     | `connext_dds_env_7.3/`  | 7.3.1       |
| 7.7.x (default)    | 3.10    | `connext_dds_env/`      | 7.7.0       |

It will:

- detect `NDDSHOME` (or use `$NDDSHOME` if already set/exported)
- detect the Connext version and select the matching Python/venv/`rti.connext` above
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

## CLI

The app entrypoint accepts:

```text
-d, --domain          DDS domain ID
-i, --interval        Refresh interval in seconds (default: 10)
--debug-log           Optional log file for discovery/subscription events
--scan-timeout        Seconds to scan for active domains before prompting (default: 32.0)
--no-domain-scan      Skip scanning for active domains before prompting
```

Direct invocation:

```bash
./connext_dds_env/bin/python tools/rti_spy/rtispy.py --domain 1
```

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

## Testing

Run the startup tests:

```bash
PYTHONPATH=tools/rti_spy ./connext_dds_env/bin/python -m unittest tools/rti_spy/test/test_startup_live.py
```

Run the discovery/subscription integration test:

```bash
PYTHONPATH=tools/rti_spy ./connext_dds_env/bin/python -m unittest tools/rti_spy/test/test_live_e2e_integration.py
```
