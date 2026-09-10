# Copilot Workspace Instructions

## RTI Connext DDS Tooling

For questions, design tasks, code reviews, implementations, debugging, or build issues involving DDS, RTI Connext, or RTI infrastructure services, use RTI MCP tools selectively based on the task. Do not query Connext AI automatically; use it only when the user explicitly asks for it.

- Use `ask_connext` / `mcp_rti_mcp_ask_connext_question` only when the user explicitly requests a Connext AI query for DDS, RTI Connext APIs, QoS, code generation, build setup, or infrastructure services behavior.
- Use RTI MCP code validation tools when reviewing or modifying DDS-related code, including `mcp_rti_mcp_validate_modern_cpp_code` for modern C++ DDS code and `mcp_rti_mcp_validate_xml_code` for Connext XML configuration.
- Use RTI MCP installation, environment, and support tools when the task depends on the local Connext installation, architecture, environment variables, generated type support, or RTI services configuration.

Use the RTI-specific tooling when it materially helps the task, but do not treat Connext AI queries as mandatory for DDS, Connext, or RTI infrastructure services related work.

## Runtime Testing

Run all runtime tests that require RTI Connext DDS, its Python API, generated
types, or RTI services in the Connext 7.7 container. Do not use a host Python
virtual environment for runtime validation.

From the repository root, build and run the container with:

```bash
export RTI_LICENSE_HOST_PATH="${RTI_LICENSE_HOST_PATH:-$HOME/rti_license.dat}"
test -r "$RTI_LICENSE_HOST_PATH"
mkdir -p shared
install -m 600 "$RTI_LICENSE_HOST_PATH" shared/rti_license.dat
docker compose -f docker-compose.connext-7.7.yml build
docker compose -f docker-compose.connext-7.7.yml run --rm connext <command>
```

Compose mounts `shared/` at `/shared`, where the container reads
`/shared/rti_license.dat`. The repository is mounted at `/workspace`; commands
run through Compose use that directory as their working directory. Host-only
checks such as Markdown, shell syntax, and static analysis remain appropriate
when they do not load RTI runtime dependencies. Do not print or read
license-file contents; copy only the resolved host path into the ignored shared
directory. For tests that create repository-relative artifacts, copy the
workspace to `/tmp` inside the container before running the test:

```bash
docker compose -f docker-compose.connext-7.7.yml run --rm connext \
	bash -lc 'cp -a /workspace/. /tmp/connext-workspace && cd /tmp/connext-workspace && <command>'
```

## rti_view Debug Logging

When debugging `rti_view` interactive or plot issues, run it in the Connext
7.7 container with `--debug`:

```
docker compose -f docker-compose.connext-7.7.yml run --rm connext \
	./tools/rti_view/run_rti_view.sh -d <domain> --debug test_output/rti_view_debug.log
```

Debug logs are written to `test_output/` within the workspace. To inspect the latest debug session, read the most recent `rti_view_debug*.log` file in `test_output/`. The log includes timestamped entries for subscribe, pump, field_select, mode, and sync_view operations with buffer stats (message count, point count, skipped_non_numeric, value types, axis ranges).
