# RTI Doctor Command-Line Reference

The normal operator entrypoint is:

```bash
./tools/rti_doctor/run_rti_doctor.sh
```

It prompts for a domain and opens the interactive diagnostic workspace.

## Headless Reports

Run system assessment before a topic diagnosis. The first stage is inexpensive;
the second can create a probe, wait for type resolution, and capture traffic.

```bash
./tools/rti_doctor/run_rti_doctor.sh --domain 1 --system --output system.txt
./tools/rti_doctor/run_rti_doctor.sh --domain 1 --topic SensorData
./tools/rti_doctor/run_rti_doctor.sh --domain 1 --topic SensorData --pcap session.pcapng
```

## Options

| Option | Purpose |
| --- | --- |
| `-d`, `--domain` | DDS domain ID; prompts interactively and defaults to `1` noninteractively. |
| `--system` | Assess discovery, topology, and local configuration, then exit. |
| `-t`, `--topic` | Diagnose one topic, then exit. Mutually exclusive with `--system`. |
| `-o`, `--output` | Write the plain-text report to a path rather than stdout. |
| `--no-probe` | Run only static checks; do not create a probe endpoint. |
| `--no-probe-default` | Leave TUI endpoint reports passive until `p` is pressed. |
| `--no-isolate-probe` | Let a probe observe all endpoints on the topic rather than only the selected endpoint. |
| `--no-network-capture` | Disable RTI Network Capture for the probe participant. |
| `--write-samples` | Permit a headless probe to publish synthetic samples to a selected reader. |
| `--pcap PATH` | Analyze RTPS data from an existing PCAP/PCAPNG; requires `--topic`. |
| `--theme NAME` | Choose a Textual theme, for example `textual-light`. |
| `--debug-log PATH` | Write Doctor discovery/probe diagnostics. |
| `--connext-log PATH` | Write native Connext diagnostics. Combine with `--connext-verbosity`. |

Timing options are `--probe-timeout`, `--type-wait`, `--settle`,
`--scan-timeout`, and `--interval`. Advanced compatibility options are
`--type-object-v1-only` and `--xtypes-compliance {default,vendor}`. Test
orchestration hooks are `--ready-file`, `--ready-after-participants`, and
`--ready-timeout`.

## Exit Status

| Code | Meaning |
| --- | --- |
| `0` | A diagnosis completed with no ERROR-severity findings. |
| `1` | A diagnosis completed with one or more ERROR-severity findings. |
| `2` | The named topic was not found. |
| `3` | `--ready-after-participants` did not complete before `--ready-timeout`. |
| `4` | Doctor could not start, including invalid arguments and startup failures. |
| `130` | Interrupted with `Ctrl-C`. |