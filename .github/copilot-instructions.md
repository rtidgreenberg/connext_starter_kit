# Copilot Workspace Instructions

## RTI Connext DDS Tooling

For any question, design task, code review, implementation, debugging, or build issue involving DDS, RTI Connext, RTI infrastructure services, or RTI Rapid Prototyping, use the available RTI MCP tools before answering or changing code:

- Use `ask_connext` / `mcp_rti_mcp_ask_connext_question` to ask for authoritative information about DDS, RTI Connext APIs, QoS, code generation, build setup, and infrastructure services behavior.
- Use RTI MCP code validation tools when reviewing or modifying DDS-related code, including `mcp_rti_mcp_validate_modern_cpp_code` for modern C++ DDS code and `mcp_rti_mcp_validate_xml_code` for Connext XML configuration.
- Use RTI MCP installation, environment, and support tools when the task depends on the local Connext installation, architecture, environment variables, generated type support, or RTI services configuration.

Treat this as mandatory for DDS, Connext, or RTI infrastructure services related work, including Recording Service, Replay Service, Converter Service, Routing Service, XML Application Creation, QoS XML, IDL, generated type support, and wrapper-class based applications.

When the user types "@rti_dev" or asks about RTI Rapid Prototyping, follow the instructions in `.github/prompts/rti_dev.prompt.md`.

On startup or when asked to initialize:
1. Check if `planning/project.yaml` exists
2. If not, trigger the framework selector workflow from `.github/prompts/rti_dev.prompt.md`
3. If it exists, check for `planning/system_config.yaml` and route accordingly
