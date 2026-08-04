# Python Runtime Setup Plan

Staged implementation plan for making every repository Python launcher detect
its dependencies and offer a supported package-installation path. The plan
covers Python applications, examples, and tools that import
`rti.connextdds`.

## Goal

Support these runtime paths through one shared launcher contract:

| Source | Intended user | Installation behavior | License behavior |
|---|---|---|---|
| Existing package | User whose virtual environment is already configured | Verify a compatible installed package | Preserve its existing configuration |
| PyPI | User with network access and an RTI license file | Install `rti.connext==<version>` from PyPI | Require and validate `RTI_LICENSE_FILE` |
| Activated wheel | User with an RTI Connext Professional installation or supplied activated wheel | Install `rti.connext.activated` from a local wheel | No separate license-file configuration |

The activated-wheel path is a **no separate license-file** workflow. It must
not be described as license-free: use and redistribution remain governed by
the applicable RTI license terms.

## Scope

### Included Launchers

- `apps/python/*/run.sh`
- `apps/python/install.sh`
- `tools/rti_view/run_rti_view.sh`
- `tools/rti_doctor/run_rti_doctor.sh`
- `tools/rti_spy/run_rtispy.sh`
- `tools/rti_spy/install.sh`
- `services/rs_gui/run_rs_gui.sh`
- `scripts/python_env.sh`

### Native Tooling Boundary

The Python API package supplies `rti.connextdds`; it does not provide native
Connext executables such as `rtiddsgen`.

- Tools that only use the Python API must work without `NDDSHOME` when the
  PyPI package and a license file are available.
- Application examples always regenerate Python type support during
  initialization and therefore require a native Connext installation with
  `rtiddsgen`.
- C++ applications and DDS infrastructure services are out of scope because
  they require a native Connext installation.

## User Interface Contract

The shared helper will support both interactive and unattended use.

### Environment Variables

| Variable | Values | Meaning |
|---|---|---|
| `RTI_PYTHON_SOURCE` | `auto`, `pypi`, `activated-wheel` | Select package source; default is `auto` |
| `RTI_PYTHON_WHEEL` | Path to `.whl` | Explicit activated-wheel location |
| `RTI_LICENSE_FILE` | Path to RTI license file | Required by the PyPI package path |

### Auto Mode

1. Use a compatible package already installed in the selected virtual
   environment.
2. Prefer an activated wheel explicitly supplied in `RTI_PYTHON_WHEEL`.
3. When `NDDSHOME` is available, look for the matching bundled activated wheel
   in `$NDDSHOME/resource/python_api/`.
4. If no package source is available and stdin is interactive, prompt the user
   to select PyPI, a local activated wheel, or cancel.
5. If stdin is not interactive, fail without prompting and print the exact
   `RTI_PYTHON_SOURCE` command required to proceed.

### Explicit Source Rules

- `RTI_PYTHON_SOURCE=pypi` never requires `NDDSHOME` solely to install the
  Python API. It validates `RTI_LICENSE_FILE` after installation.
- `RTI_PYTHON_SOURCE=activated-wheel` uses `RTI_PYTHON_WHEEL` first, then a
  matching wheel discovered under `NDDSHOME`. It fails with the expected wheel
  name and Python tag if neither exists.
- Source selection must be deterministic in non-interactive environments.
- Existing packages are verified for compatibility; a mismatched package must
  not silently run against generated types or native tooling from another
  Connext version.

## Stage 1: Define and Test the Shared Source Contract

**Goal:** Make package source selection explicit without changing existing
launcher behavior yet.

**Primary artifact:** `scripts/python_env.sh`

### Tasks

| ID | Task | Description |
|---|---|---|
| P1.1 | Define source constants | Add `auto`, `pypi`, and `activated-wheel` as the supported values for `RTI_PYTHON_SOURCE`. Reject unknown values with a clear error. |
| P1.2 | Detect interactive execution | Add a helper that distinguishes a terminal from CI, container entrypoints, and redirected stdin. |
| P1.3 | Discover installed distributions | Detect both `rti.connext` and `rti.connext.activated`, including their installed versions. |
| P1.4 | Select a source | Add a single helper that applies the auto-mode order and records the chosen source. |
| P1.5 | Prompt only when allowed | Present a numbered prompt only after package discovery fails and only for an interactive run. |
| P1.6 | Add shell tests | Cover valid sources, invalid sources, auto-mode ordering, and non-interactive failure behavior. |

### Acceptance Criteria

- No launcher prompts in CI or when stdin is redirected.
- A non-interactive failure states both the missing condition and an executable
  remediation command.
- An existing compatible distribution is selected without running `pip`.
- Tests can inject package-discovery and terminal-detection behavior without
  contacting PyPI or requiring a real wheel.

## Stage 2: Implement PyPI and Activated-Wheel Installation

**Goal:** Install the selected package source safely and efficiently in the
shared virtual environment.

**Depends on:** Stage 1

### Tasks

| ID | Task | Description |
|---|---|---|
| P2.1 | Preserve venv selection | Keep current Python-version and venv selection for native Connext installations; define a default interpreter/version policy for a PyPI-only invocation. |
| P2.2 | Install from PyPI | Install the selected `rti.connext` version only when it is absent or incompatible. |
| P2.3 | Install local activated wheel | Accept `RTI_PYTHON_WHEEL`, validate it is a wheel, and install it without network access. |
| P2.4 | Retain bundled-wheel discovery | Keep the current matching-wheel lookup under `$NDDSHOME/resource/python_api/` as a secondary activated-wheel source. |
| P2.5 | Preserve metadata cleanup | Continue removing stale `rti.connext` or `rti.connext.activated` metadata before switching distributions. |
| P2.6 | Preserve local-wheel fast path | Use distribution metadata to skip a matching local wheel rather than invoking `pip install <wheel>` on every launch. |

### Acceptance Criteria

- `RTI_PYTHON_SOURCE=pypi` installs without `NDDSHOME`.
- `RTI_PYTHON_SOURCE=activated-wheel RTI_PYTHON_WHEEL=/path/to/wheel.whl`
  installs without network access.
- Repeating either path does not reinstall a compatible package.
- Switching from PyPI to activated wheel, and back, leaves only the selected
  distribution metadata in the virtual environment.

## Stage 3: License and Native-Tooling Policy

**Goal:** Apply license checks only to the appropriate runtime source and make
native-tooling errors precise.

**Depends on:** Stage 2

### Tasks

| ID | Task | Description |
|---|---|---|
| P3.1 | Gate license resolution | Call `python_env_resolve_license_file` only for the PyPI source. Activated wheels skip that lookup and announce why. |
| P3.2 | Make license errors actionable | For PyPI runs, report the missing or invalid `RTI_LICENSE_FILE` and show the export syntax. |
| P3.3 | Regenerate type support | Regenerate all Python type support during initialization; never reuse generated source files or a prior runtime cache. |
| P3.4 | Gate type generation | Require `rtiddsgen` from a valid native installation and identify the expected executable path before generation. |
| P3.5 | Classify launchers | Mark each launcher as Python-only, generated-types optional, or native-tooling required for its selected operation. |

### Acceptance Criteria

- A Python-only tool runs from PyPI with a valid `RTI_LICENSE_FILE` and no
  `NDDSHOME`.
- An activated wheel path does not demand an unrelated license-file setting.
- An example fails specifically on missing `rtiddsgen`, not on generic
  `NDDSHOME` detection.
- Every application initialization regenerates type support for the selected
  Python API version.

## Stage 4: Migrate Launchers

**Goal:** Route every supported Python entry point through the shared contract.

**Depends on:** Stages 1-3

### Tasks

| ID | Launcher group | Required change |
|---|---|---|
| P4.1 | `rti_view`, `rti_doctor`, `rti_spy` | Select/install the Python API before requiring native-install discovery; retain their tool-specific requirements checks. |
| P4.2 | `apps/python/*` | Use the shared source-selection sequence, then regenerate generated type support during initialization. |
| P4.3 | `services/rs_gui` | Support Python-only UI startup; require native tooling only for `--prepare-dds` and native service diagnostics. |
| P4.4 | Install scripts | Make `apps/python/install.sh` and `tools/rti_spy/install.sh` expose the same source and license options as run scripts. |
| P4.5 | Arguments and help | Add a consistent optional `--python-source` flag only where it does not conflict with existing application arguments; environment variables remain the universal automation interface. |

### Acceptance Criteria

- All listed launchers use one shared package-source helper.
- A tool launcher has the same package-source semantics as its installer.
- Existing native-install workflows continue to select their bundled matching
  activated wheel automatically.
- Existing launcher flags retain their behavior.

## Stage 5: Documentation and Deployment Recipes

**Goal:** Make both supported deployment paths easy to discover and safe to
automate.

**Depends on:** Stage 4

### Tasks

| ID | Task | Documentation target |
|---|---|---|
| P5.1 | Update repository prerequisites | `README.md` |
| P5.2 | Document Python app setup | `apps/python/README.md` and relevant app READMEs |
| P5.3 | Document tool setup | `tools/README.md`, `tools/rti_view/README.md`, `tools/rti_doctor/README.md`, and `tools/rti_spy/README.md` |
| P5.4 | Document GUI setup | `services/rs_gui/README.md` |
| P5.5 | Add unattended examples | Include environment-variable examples for CI, containers, and air-gapped activated-wheel deployments. |

### Required Recipes

PyPI with license file:

```bash
RTI_PYTHON_SOURCE=pypi \
RTI_LICENSE_FILE=/secure/path/rti_license.dat \
./tools/rti_doctor/run_rti_doctor.sh
```

Activated wheel with no separate license-file configuration:

```bash
RTI_PYTHON_SOURCE=activated-wheel \
RTI_PYTHON_WHEEL=/opt/rti-wheels/rti_connext_activated-<version>-cp<python>-<platform>.whl \
./tools/rti_doctor/run_rti_doctor.sh
```

### Acceptance Criteria

- Documentation distinguishes Python-only tools from native Connext
  requirements.
- Every recipe identifies whether it needs network access, a license file, or
  a local activated wheel.
- The activated-wheel language says "no separate license-file configuration,"
  not "license-free."

## Stage 6: End-to-End Validation and Rollout

**Goal:** Validate the complete user experience before making the new behavior
the documented default.

**Depends on:** Stages 1-5

### Test Matrix

| Scenario | Expected result |
|---|---|
| Compatible installed package | Launcher runs with no prompt and no `pip` operation. |
| Interactive, no package/source | User sees a source-selection prompt. |
| Non-interactive, no package/source | Launcher exits with a deterministic remediation command. |
| Explicit PyPI with valid license | Installs/imports package and launches a Python-only tool without `NDDSHOME`. |
| Explicit PyPI without valid license | Fails after install with a clear `RTI_LICENSE_FILE` error. |
| Explicit activated wheel | Installs/imports package without network or separate license-file lookup. |
| Native installation available | Finds and uses the bundled activated wheel matching interpreter and Connext version. |
| Missing generated types | Example explains it needs `rtiddsgen` and a native installation. |
| Existing generated types | Example removes the old output and regenerates all required types. |
| Version switch | Switching between PyPI and activated-wheel distributions does not leave conflicting metadata. |

### Rollout Criteria

- Shell unit tests pass for every new branch in `scripts/python_env.sh`.
- Focused launcher smoke tests pass for at least `rti_doctor`, `rti_view`, one
  Python example, and `rs_gui` diagnostics mode.
- Existing `rti_spy`, `rti_view`, and `rti_doctor` test suites continue to
  pass in supported local Connext environments.
- Documentation commands are executed in a clean virtual environment before
  release.

## Implementation Order

Implement and merge the stages in order. Stage 4 may migrate tools first,
then applications and the GUI, but no launcher should introduce its own
package-source logic. `scripts/python_env.sh` remains the sole owner of source
selection, package installation, and source-specific license policy.