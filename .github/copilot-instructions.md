# Copilot Workspace Instructions

## RTI Connext DDS Tooling

For questions, design tasks, code reviews, implementations, debugging, or build issues involving DDS, RTI Connext, RTI infrastructure services, or RTI Rapid Prototyping, use RTI MCP tools selectively based on the task. Do not query Connext AI automatically; use it only when the user explicitly asks for it.

- Use `ask_connext` / `mcp_rti_mcp_ask_connext_question` only when the user explicitly requests a Connext AI query for DDS, RTI Connext APIs, QoS, code generation, build setup, or infrastructure services behavior.
- Use RTI MCP code validation tools when reviewing or modifying DDS-related code, including `mcp_rti_mcp_validate_modern_cpp_code` for modern C++ DDS code and `mcp_rti_mcp_validate_xml_code` for Connext XML configuration.
- Use RTI MCP installation, environment, and support tools when the task depends on the local Connext installation, architecture, environment variables, generated type support, or RTI services configuration.

Use the RTI-specific tooling when it materially helps the task, but do not treat Connext AI queries as mandatory for DDS, Connext, or RTI infrastructure services related work.

When the user types "@rti_dev" or asks about RTI Rapid Prototyping, follow the instructions in `.github/prompts/rti_dev.prompt.md`.

On startup or when asked to initialize:
1. Check if `planning/project.yaml` exists
2. If not, trigger the framework selector workflow from `.github/prompts/rti_dev.prompt.md`
3. If it exists, check for `planning/system_config.yaml` and route accordingly

## rti_view Debug Logging

When debugging `rti_view` interactive or plot issues, run with `--debug`:

```
python -m rti_view -d <domain> --debug test_output/rti_view_debug.log
```

Debug logs are written to `test_output/` within the workspace. To inspect the latest debug session, read the most recent `rti_view_debug*.log` file in `test_output/`. The log includes timestamped entries for subscribe, pump, field_select, mode, and sync_view operations with buffer stats (message count, point count, skipped_non_numeric, value types, axis ranges).
