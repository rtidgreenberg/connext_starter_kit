---
mode: agent
description: "Clear generated log folders in this workspace"
---

# Clear Generated Log Folders

Clear generated runtime and GUI log output from this workspace while preserving the folder structure.

## Safety Rules

- Work from the workspace root.
- Remove only generated log files and generated log subdirectories.
- Keep the target folders themselves in place.
- Do not delete source files, configuration files, virtual environments, dependency caches, vendored dependencies, or build-system metadata.
- Do not touch these false positives:
  - `apps/dist_logger_tst/`
  - `build/_deps/**/.git/logs/`
  - `connext_dds_env/**/rti/logging/`

## Default Targets

Clean these directories when they exist:

- `log_dir/`
- `services/rs_gui_v1/log_dir/`
- `services/rs_gui_v2/rs_gui_logs/`
- `services/rs_gui_v2/service_logs/`
- `services/rs_gui_v2/service_churn/run_*/log_dir/`
- `test_output/rs_gui_v2/service_churn/run_*/log_dir/`

If the user explicitly asks to clear test artifacts too, also clear generated contents under `test_output/rs_gui_v2/` while keeping the `test_output/` directory tree itself.

## Workflow

1. Preview the matching targets before deleting anything:

   ```bash
   find log_dir \
     services/rs_gui_v1/log_dir \
     services/rs_gui_v2/rs_gui_logs \
     services/rs_gui_v2/service_logs \
     services/rs_gui_v2/service_churn/run_*/log_dir \
     test_output/rs_gui_v2/service_churn/run_*/log_dir \
     -mindepth 1 -maxdepth 1 -print 2>/dev/null | sort
   ```

2. If matches are present, ask the user for confirmation before deleting unless their request already clearly confirms cleanup.

3. Delete only the matched contents:

   ```bash
   find log_dir \
     services/rs_gui_v1/log_dir \
     services/rs_gui_v2/rs_gui_logs \
     services/rs_gui_v2/service_logs \
     services/rs_gui_v2/service_churn/run_*/log_dir \
     test_output/rs_gui_v2/service_churn/run_*/log_dir \
     -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + 2>/dev/null
   ```

4. Verify the cleanup by listing any remaining contents in the default target folders.

5. Report which folders were cleaned and whether anything was skipped because it did not exist.