# RTI Spy PyInstaller Bundle and Theme Plan

## Background

`rti_spy` needs an offline, portable deployment workflow. The initial target
is Connext 7.3 with Python 3.9.

A manual PyInstaller build of `rti_spy` worked after adding explicit RTI hidden
imports, including `rti.idl_impl`. That runtime dependency needs to be captured
by the supported `rti_spy` packaging path rather than rediscovered manually.
`rti_spy` also needs a command-line option to select its initial Textual
palette.

## Scope

This first release supports only `tools/rti_spy`. Extending the bundle tooling
to other Python applications is deferred until the `rti_spy` bundle is
validated on a target system.

## Goals

- Provide a repeatable PyInstaller folder-bundle deployment workflow for
  `rti_spy`.
- Support portable bundles built with Connext 7.3 and Python 3.9.
- Use a local RTI Python wheel without requiring PyPI during offline
  setup or packaging.
- Produce a compressed PyInstaller folder bundle as the deployable artifact.
- Add an initial Textual theme option to `rti_spy`.

## Build Interface

The user supplies an RTI Python wheel during preparation. The build
script reuses the recorded wheel:

```bash
./scripts/build_rti_spy_bundle.sh
```

The build tool must parse the wheel filename and metadata to derive the
Connext package version, Python ABI tag, and target architecture. It then
selects the compatible installed Python interpreter and validates the
combination before creating a virtual environment. `NDDSHOME`, a Connext
version, a Python version, and library locations are not required user inputs.
The tool may use `NDDSHOME` only as an optional source of native resources;
when it cannot obtain required resources from the wheel or standard system
locations, it must report the exact missing path rather than prompt for broad
environment configuration.

## User Workflow

The workflow has two deliberate stages. The first runs on a connected build
machine and obtains non-RTI dependencies. The second packages and deploys the
application without downloading the RTI Python API.

1. Prepare a matching build environment while online.
  - Install the Python interpreter and shared library required by the RTI Python wheel (Python
     3.9 for a Connext 7.3 `cp39` wheel).
   - Create the build virtual environment.
   - Install `rti_spy` requirements and PyInstaller from the repository's
     approved package source.
  - Install the user's local RTI Python wheel into that environment.

2. Build the deployable artifact.
   - Run `./scripts/build_rti_spy_bundle.sh`.
  - The script reuses the RTI Python wheel recorded by preparation. To use a
    different wheel, rerun the preparation step with that wheel.
   - The tool builds a one-folder PyInstaller distribution and emits one
     `.tar.gz` archive.

3. Deploy and run.
   - Copy and extract the `.tar.gz` on a compatible target Linux system.
   - Invoke the bundled executable with the application's normal command-line
     arguments.
   - The target does not require Python, pip, the source repository, or the
    RTI Python wheel. It must have compatible CPU architecture, glibc, and
     system graphics/runtime support where the packaged application needs it.

## Non-goals

- Add Python 3.9 support for Connext 7.7. Connext 7.7 requires Python 3.10
  or newer.
- Promise portability across incompatible CPU architectures, Linux/glibc
  versions, Connext versions, or licensing configurations.
- Remove existing application launch scripts or interactive theme controls.
- Package applications other than `rti_spy` in this first release.

## Implementation Steps

1. Confirm and preserve shared runtime selection in `scripts/python_env.sh`.
   - Keep Connext 7.3 mapped to Python 3.9 and the matching `cp39` activated
     wheel.
   - Keep Connext 7.7 mapped to Python 3.10 or newer.
   - Preserve versioned virtual environments and explicit
     `RTI_PYTHON_SOURCE=activated-wheel` plus `RTI_PYTHON_WHEEL` behavior.

2. Add `rti_spy` packaging tooling under `scripts/`.
   - Add `prepare_rti_spy_bundle_env.sh` for the connected-machine setup of
     Python dependencies and PyInstaller.
   - Add `build_rti_spy_bundle.sh`, which reuses the prepared RTI Python wheel.
   - Derive the Connext version, Python ABI tag, and target architecture from
     wheel metadata. Select and validate the matching installed interpreter;
     do not require `--connext-version`, `--python`, `--nddshome`, or
     `--library-dir` arguments.
   - Use the prepared `rti_spy` virtual environment and build `rtispy.py` as a
     one-folder PyInstaller distribution. The build script must not download
     packages.
   - Write temporary build files and final archives to an ignored deployment
     output directory, not application source directories.
   - Create a `.tar.gz` archive containing the complete executable folder.
   - Include the Connext version, Python ABI, and build architecture in the
     archive filename.
  - Always use the supplied local RTI Python wheel and fail before any package
     operation that would need network access.

3. Add an `rti_spy` PyInstaller collection hook.
   - Include runtime-loaded RTI modules identified by the successful `rti_spy`
     build: `rti.asyncio`, `rti.connextdds`, `rti.idl`, `rti.idl_impl`,
     `rti.libnddsc`, `rti.libnddscore`, `rti.libnddscpp2`, `rti.logging`,
     `rti.request`, `rti.rpc`, and `rti.types`.
   - Collect native RTI libraries and package data required by the selected
    RTI Python wheel.
   - Add `rti_spy` resources and dynamically imported modules to the hook, and
     fail the build if a required resource is absent.

4. Add focused automated coverage.
   - Test Connext 7.3 selection of Python 3.9 with a matching `cp39`
    RTI Python wheel.
   - Test wheel metadata parsing, interpreter selection, and clear failures
     for an unsupported ABI tag or missing matching interpreter.
   - Test explicit `RTI_PYTHON_SOURCE=activated-wheel` and
     `RTI_PYTHON_WHEEL` selection.
   - Test prepared-environment validation, no-download build behavior, and
     archive layout without requiring live DDS traffic.

5. Add `rti_spy` initial-theme support.
   - Add `--theme` with a Textual theme name argument.
   - Validate the requested theme against themes registered by the installed
     Textual version before DDS participant creation.
   - Apply the selected theme to the `RTISPY` instance before `app.run()`.
   - Retain the existing interactive palette controls.

6. Document the `rti_spy` deployment workflow.
   - Update `tools/rti_spy/README.md` with the online dependency-preparation
  stage, local RTI Python wheel installation, non-interactive build command,
  and target compatibility limits.
   - Document `rti_spy --theme <name>` and the installed light-theme name.

## Validation

1. Run focused shell tests for Python 3.9 and activated-wheel selection under
   Connext 7.3.
2. Build an `rti_spy` bundle using a local RTI Python wheel after the build
   environment is prepared; verify that the build does not access the network.
3. Extract the generated archive in a clean temporary directory and execute
  its non-interactive help or startup smoke command.
4. Run existing `rti_spy` startup tests.
5. Run live DDS participant discovery and DynamicData traffic checks to verify
  `rti.idl_impl` is present at runtime.
6. Verify valid and invalid `rti_spy --theme` values before and after the
   PyInstaller build.

## Acceptance Criteria

- The `rti_spy` preparation interface requires an RTI Python wheel path and
  derives Connext and Python versions from the wheel.
- A compatible Connext 7.3 installation with a `cp39` RTI Python wheel can
  build `rti_spy` without downloading `rti.connext` from PyPI.
- Each build produces a compressed, self-contained application folder.
- Each archive filename identifies its Connext version, Python ABI, and build
  architecture.
- Extracted bundles start on a compatible target and include their required
  native RTI dependencies, data files, and dynamically imported modules.
- `rti_spy` discovers participants and receives DDS traffic from the deployed
  bundle without an `rti.idl_impl` import failure.
- `rti_spy --theme <name>` starts with a valid requested Textual palette, and
  invalid names fail before a DDS participant is created.