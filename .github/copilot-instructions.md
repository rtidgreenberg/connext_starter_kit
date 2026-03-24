# Copilot Workspace Instructions

When the user types "@rti_dev" or asks about DDS process building, follow the instructions in `.github/prompts/rti_dev.prompt.md`.

On startup or when asked to initialize:
1. Check if `planning/project.yaml` exists
2. If not, trigger the framework selector workflow from `.github/prompts/rti_dev.prompt.md`
3. If it exists, check for `planning/system_config.yaml` and route accordingly
