# Project context for Claude Code

## Running Python tests

**Never invoke `python3` or `pytest` directly.** The system interpreter is Python
3.8; this project targets 3.11 and uses `str.removeprefix` and
`asyncio.to_thread`, which 3.8 does not have. A bare `python3 -m pytest` run
therefore produces dozens of failures that are entirely artifacts of the wrong
interpreter — a red suite that says nothing about the code.

Use the tool's own runner, which resolves `NDDSHOME`, the venv and the license
itself:

```bash
./tools/rti_doctor/run_tests.sh          # unit (the default) — the tier CI runs
./tools/rti_doctor/run_tests.sh live     # unit + live domain: needs a license
./tools/rti_doctor/run_tests.sh vendor   # cross-vendor e2e: needs Docker images
./tools/rti_doctor/run_tests.sh all      # everything
```

Report a change as tested only against `run_tests.sh`. The whole run is kept at
`tools/rti_doctor/test_output/run_tests_<tier>.log`; the terminal shows a 40-line
tail, so on a red run read the log rather than the tail.

To run a single module as a diagnostic, use the venv interpreter the launcher
built — do not hardcode its path. The directory name encodes the resolved
Connext and Python versions (`connext_dds_env_7.7_py311` today) and changes with
them, so resolve it:

```bash
export VENV_PYTHON=$(ls -d connext_dds_env_*/bin/python | head -1)
PYTHONPATH=tools/rti_doctor "$VENV_PYTHON" \
    -m unittest discover -s tools/rti_doctor/test -p 'test_checks.py'
```

`scripts/python_env.sh` is the shared resolver behind all of this. Anything that
needs the Connext Python binding should go through it rather than picking an
interpreter on its own.

More detail, including what each tier needs and why they are separate, is in
[tools/rti_doctor/README.md](tools/rti_doctor/README.md).
