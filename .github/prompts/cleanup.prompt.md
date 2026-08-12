---
name: "cleanup"
description: "Thoroughly inspect this repository and safely remove build caches, test output, diagnostic logs, captures, recordings, and other generated artifacts"
argument-hint: "Optional scope or directories to clean"
agent: "agent"
---

Safely and thoroughly clean generated artifacts in this repository. Optional requested scope: ${input:scope:all generated artifacts}.

1. Establish the safety boundary.
	- Resolve and remain inside the repository root. Do not follow symlinks outside it.
	- Run `git status --short` and record all existing tracked and untracked changes before proposing deletions.
	- Inspect the root and nested `.gitignore` files plus relevant build, test, recording, and service scripts to identify each artifact's producer.
	- Before listing any candidate, use Git to verify that no file under it is tracked. Never delete a tracked file, even when its name or parent matches a generated-artifact pattern.

2. Inventory every applicable generated-artifact class, including nested instances:
	- CMake and compiler output: `build/`, application build directories, `CMakeFiles/`, `CMakeCache.txt`, generated Makefiles/Ninja files, object files, libraries, executables, and compile databases produced by a build.
	- Generated DDS type support and code generation output when its owning build or setup command can recreate it.
	- Python caches and test caches outside virtual environments and dependency trees: `__pycache__/`, `*.pyc`, `*.pyo`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.tox/`, and `.nox/`.
	- Coverage and packaging output: `.coverage*`, `coverage.xml`, `htmlcov/`, `dist/`, package build directories, and generated metadata.
	- All test output directories, including every nested `test_output/` tree, test-run workspaces, fixture readiness markers, integration-test run directories, and service-churn test artifacts.
	- All diagnostic and runtime logs that are not tracked, including `*.log`, `*.log.*`, `*.jsonl`, `debug_logs/`, `service_logs/`, `rs_gui_logs/`, `live_reports/`, `manual_debug/`, and tool debug logs.
	- Packet and diagnostic captures that are not tracked, including `*.pcap`, `*.pcapng`, and associated tshark output.
	- Recording, replay, and conversion output that is not tracked, including `services/log_dir/`, `services/converted/`, `services/rs_gui/log_data/`, recording workspaces, XCDR data, SQLite/database files such as `*.db`, and generated `*.dat` files.
	- Temporary and editor artifacts such as `*.tmp`, `*.temp`, backup files, crash dumps, and abandoned empty generated directories.

3. Treat diagnostic logs, test outputs, packet captures, and recording databases as disposable cleanup candidates. They do not require a separate manual-review classification merely because they may contain diagnostic evidence. Still exclude any tracked file and list the concrete paths before deletion.

4. Protect environments and non-generated data.
	- Do not delete virtual environments such as `connext_dds_env*`, dependency/vendor trees, credentials, source, configuration, documentation, or user-authored data unless the user explicitly names that path.
	- Do not classify a path as disposable solely because Git ignores it. If ownership or reproducibility is unclear and it is not one of the explicitly disposable classes above, retain it for manual review.

5. Present one concise cleanup plan before deleting anything. Group candidates by class, list every concrete path or clearly bounded path pattern, explain its producer, show file count and estimated size, and state the total estimated reclaimable size. Ask for explicit confirmation.

6. After confirmation, remove only the approved paths with narrowly scoped commands. Do not use `git clean -fdx`, `git reset --hard`, `rm -rf .`, repository-wide extension wildcards, or deletion outside the approved repository paths. Recheck tracked-file status immediately before deletion if the plan is no longer current.

7. Verify completion.
	- Rescan all artifact classes from step 2 and report any remaining candidates and why they were retained.
	- Report each removed path group, actual reclaimed space, and the final `git status --short`.
	- Confirm that all pre-existing source and working-tree changes remain present and unchanged.

If no safe candidates exist, report that result without deleting anything.