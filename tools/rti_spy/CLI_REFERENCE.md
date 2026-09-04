# RTI Spy Command-Line Reference

The normal operator entrypoint is:

```bash
./tools/rti_spy/run_rtispy.sh
```

Without `--domain`, an interactive launch prompts for a domain or offers to scan
for active Connext domains first. Noninteractive launches use domain `1`.

## Options

| Option | Purpose |
| --- | --- |
| `-d`, `--domain ID` | Open a DDS domain directly. |
| `-i`, `--interval SECONDS` | Set UI refresh interval; default `10`. |
| `--debug-log PATH` | Write discovery and subscription diagnostics to a file. |
| `--scan-timeout SECONDS` | Limit active-domain scanning; default `32.0`. |
| `--no-domain-scan` | Skip the active-domain scan before prompting. |
| `--theme NAME` | Choose the initial Textual theme, for example `textual-light`. |

Examples:

```bash
./tools/rti_spy/run_rtispy.sh --domain 1 --theme textual-light
./tools/rti_spy/run_rtispy.sh --domain 42 --debug-log test_output/rti_spy.log
```

## Direct Invocation

Prefer the launcher because it selects the matching Connext Python environment
and resolves the license. When that environment is already available, run:

```bash
./connext_dds_env_7.7_py311/bin/python tools/rti_spy/rtispy.py --domain 1
```