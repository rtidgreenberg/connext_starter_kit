# Use-Case Dry Runs & Gap Analysis

Two end-to-end walkthroughs of the `/rti_dev` workflow executed against the
README use cases. Each step records what the agent would do, what artifacts it
needs, and whether those artifacts exist today.

---

## Use Case 1: "I want to send large data over SHMEM with Python"

README link: *I want to transfer large data efficiently with shared memory*

Target output should resemble `apps/python/large_data_app/` — a Python async
app that publishes/subscribes ~900 KB images over shared-memory transport using
`DataPatternsLibrary::LargeDataSHMEMQoS`.

### Phase 0 — Project Init

| Step | Agent Action | Artifact Needed | Exists? |
|------|-------------|-----------------|---------|
| Detect state | Check for `planning/project.yaml` | – | ✅ Logic in rti_dev.prompt.md |
| Framework prompt | Ask: "Wrapper Class or XML App Creation?" | rti_dev.prompt.md | ⚠️ Basic — works for this step |
| User answer | "Wrapper Class" | – | – |
| API prompt | Ask: "Which API?" | rti_dev.prompt.md | ⚠️ Basic — works for this step |
| User answer | "Python" | – | – |
| Write project.yaml | Create `planning/project.yaml` with `framework: wrapper_class, api: python` | project.yaml.example (schema reference) | ✅ |
| Derive fields | `rtiddsgen_language: Python`, `build_system: pip`, `app_dir: apps/python` | Derivation rules in docs/02 | ✅ Documented |
| Bootstrap | Fetch reference content into `system_templates/` slots | `reference_manifest.yaml` | ❌ **GAP R0-1** |

**Gap R0-1: No bootstrap mechanism.** Phase 0 docs describe a one-time
bootstrap that populates `system_templates/` from GitHub sources. The
`reference_manifest.yaml` that drives it doesn't exist. For this dry run the
agent would need QoS fragments and blueprint code already in place — which they
aren't.

**Gap R0-2: Python + Wrapper Class combination ambiguity.** The existing
Python scaffold (`system_templates/python/scaffold/`) exists separately from
the Wrapper Class scaffold. When `api: python` + `framework: wrapper_class`,
which scaffold does the agent use? The Python scaffold templates reference
`{{PROCESS_NAME}}_logic.py` (wrapper-class-style separation), which is correct.
But the manifest routing (`wrapper_class/manifest.yaml` vs
`python/manifest.yaml`) is undefined.

**Recommendation:** The `manifest.yaml` selection should use *both* dimensions:
`(framework, api)`. For `(wrapper_class, python)` → use
`system_templates/python/manifest.yaml`. For `(wrapper_class, modern_cpp)` →
use `system_templates/wrapper_class/manifest.yaml`. Add this routing table to
`docs/09_repository_structure.md`.

---

### Phase 1 — System Design

| Step | Agent Action | Artifact Needed | Exists? |
|------|-------------|-----------------|---------|
| Domain ID | Ask user; user picks default (0) | – | ✅ Prompt handles this |
| System patterns | Ask user; user picks **none** (simple large data demo) | System patterns catalog | ✅ docs/07 |
| Write system_config.yaml | `domain_id: 0, system_patterns: []` | system_config.yaml.example | ✅ |

No gaps for this simple case. System patterns are optional.

---

### Phase 2 — System Implementation

| Step | Agent Action | Artifact Needed | Exists? |
|------|-------------|-----------------|---------|
| Read system_manifest.yaml | Load generation rules | `system_templates/system_manifest.yaml` | ❌ **GAP R2-1** |
| Create directories | `apps/python/`, `dds/datamodel/idl/`, `dds/build/` | – | ✅ Already exist |
| Verify QoS exists | Check `dds/qos/DDS_QOS_PROFILES.xml` | – | ✅ 1073 lines |
| Skip system IDL | No system patterns selected → no system_patterns.idl | – | ✅ |
| Run Python codegen | `rtiddsgen -language Python ...` on any system IDL | – | ✅ Skipped |

**Gap R2-1: No `system_manifest.yaml`.** Without it, the agent doesn't have a
machine-readable recipe for Phase 2. An experienced agent could hard-code the
steps, but the manifest-driven design requires this file for reproducibility.

**Impact for this use case:** LOW — no system patterns means Phase 2 is
essentially "verify directories and QoS exist." But without the manifest, the
agent must improvise rather than follow a deterministic recipe.

---

### Phase 3 — Process Design

#### Step 1: Process Identity

| Step | Agent Action | Artifact Needed | Exists? |
|------|-------------|-----------------|---------|
| Name | User: "large_data_camera" | – | ✅ |
| Domain ID | Inherit from system (0) | – | ✅ |
| Transport | User: "SHMEM only" (option 2) | Transport menu in docs/05 | ✅ |
| System pattern opt-in | Skip — none configured | – | ✅ |

#### Step 2: Define I/O

**Output: Image publisher**

| Step | Agent Action | Artifact Needed | Exists? |
|------|-------------|-----------------|---------|
| Direction | Output (publish) | – | ✅ |
| Topic name | "ImageTopic" | – | ✅ |
| Type gate | "Define New or Select Existing?" | datamodel.prompt.md | ❌ **GAP R3-1** |
| User picks | "Select Existing" → agent scans IDL files | IDL scanner logic | ⚠️ Not implemented |
| Agent finds | `example_types::Image` in `ExampleTypes.idl` | – | ✅ IDL exists |
| Pattern selection | Agent auto-resolves: `sequence<octet>` > 64KB → Large Data pattern | patterns.prompt.md | ❌ **GAP R3-2** |
| Pattern option | SHMEM only transport → Option 1 (SHMEM, no zero-copy) | Auto-resolve rules in docs/07 | ✅ Documented |
| QoS profile | `DataPatternsLibrary::LargeDataSHMEMQoS` | QoS mapping table | ✅ Documented |
| Rate | User: "1 Hz" | – | ✅ |
| Callbacks | `publication_matched` (auto-assigned for writers) | – | ✅ |

**Input: Image subscriber**

| Step | Agent Action | Artifact Needed | Exists? |
|------|-------------|-----------------|---------|
| Direction | Input (subscribe) | – | ✅ |
| Topic name | "ImageTopic" (same topic — pubsub demo) | – | ✅ |
| Type | Reuse `example_types::Image` | – | ✅ |
| Pattern | Large Data, Option 1 (SHMEM) | – | ✅ |
| QoS profile | `DataPatternsLibrary::LargeDataSHMEMQoS` | – | ✅ |
| Callbacks | `data_available` (auto-assigned for readers) | – | ✅ |

**Gap R3-1: No `datamodel.prompt.md`.** The type definition gate that walks
through "Define New vs Select Existing" doesn't have a sub-prompt file yet.
The agent would need to improvise the IDL type walkthrough. For "Select
Existing" this is simpler (just scan `.idl` files), but for "Define New" the
full IDL field walkthrough, bounded string enforcement, `@key` guidance, and
live IDL preview all depend on this sub-prompt.

**Gap R3-2: No `patterns.prompt.md`.** The auto-resolve rules *are*
documented in docs/07, but no prompt file packages them for the agent. The
agent reading docs/07 directly would work but is fragile — it depends on the
orchestrator knowing to load docs/07 at step 2c.

**Gap R3-3: Participant QoS profile selection is implicit.** The
per-I/O QoS profile (`LargeDataSHMEMQoS`) is assigned correctly. But the
*participant* QoS profile (`DPLibrary::LargeDataSHMEMParticipant`) is needed
because SHMEM transport requires `message_size_max` to be configured at the
participant level for large data. The current process design schema records
per-I/O QoS but has **no field for participant-level QoS override**.

The existing Python large_data_app uses
`qos_profiles.LARGE_DATA_PARTICIPANT` — this is participant-level config
that enables the SHMEM buffer sizes needed for 900 KB images.

**CRITICAL GAP R3-4: Process design YAML has no `participant_qos_profile`
field.** Without it, Phase 4 code generation would create a participant with
the default QoS, which has `message_size_max: 65530` — far too small for
900 KB images. The SHMEM transport would silently fail or fragment the data.

**Recommendation:** Add to `PROCESS_DESIGN.yaml` schema:

```yaml
process:
  name: large_data_camera
  participant_qos_profile: "DPLibrary::LargeDataSHMEMParticipant"  # NEW FIELD
  transports: [SHMEM]
```

Or better: auto-derive the participant profile from transport + largest data
size:
- Transport includes SHMEM + any I/O has data > 64KB →
  `LargeDataSHMEMParticipant`
- Transport includes SHMEM + data is FlatData → `LargeDataSHMEMParticipant`
  (same)
- Transport is UDP only + large data → `LargeDataUDPParticipant`
- Otherwise → `DefaultParticipant`

#### Step 3: Tests

| Step | Agent Action | Artifact Needed | Exists? |
|------|-------------|-----------------|---------|
| Auto-propose unit tests | `test_image_publish`, `test_image_receive` | tester.prompt.md | ❌ **GAP R3-5** |
| Auto-propose integration | `test_large_data_camera_e2e` | tester.prompt.md | ❌ Same |
| User confirms | Accept defaults | – | ✅ |

**Gap R3-5: No `tester.prompt.md`.** Test auto-proposal rules are documented
in docs/01 (TEST-1 through TEST-5) but not packaged as a sub-prompt.

#### Step 4: Review

Agent presents full PROCESS_DESIGN.yaml. Expected output:

```yaml
process:
  name: large_data_camera
  domain_id: null  # inherit from system
  transports: [SHMEM]
  participant_qos_profile: "DPLibrary::LargeDataSHMEMParticipant"  # NEEDED
  system_config_version: 1
  system_patterns: []

idl_files:
  - dds/datamodel/idl/ExampleTypes.idl

inputs:
  - name: image_input
    topic: ImageTopic
    type: example_types::Image
    pattern: large_data
    pattern_option: 1
    qos_profile: "DataPatternsLibrary::LargeDataSHMEMQoS"
    callbacks: [data_available]

outputs:
  - name: image_output
    topic: ImageTopic
    type: example_types::Image
    pattern: large_data
    pattern_option: 1
    qos_profile: "DataPatternsLibrary::LargeDataSHMEMQoS"
    rate_hz: 1
    callbacks: [publication_matched]

tests:
  unit:
    - name: test_image_publish
      verifies: image_output
    - name: test_image_receive
      verifies: image_input
  integration:
    - name: test_large_data_camera_e2e
```

---

### Phase 4 — Process Implementation

#### Step 1: Scaffold

| Action | Artifact Needed | Exists? |
|--------|-----------------|---------|
| Read manifest | `system_templates/python/manifest.yaml` | ❌ **GAP R4-1** |
| Copy `app_main.py.template` → `apps/python/large_data_camera/large_data_camera.py` | Template file | ✅ Exists |
| Copy `process_logic.py.template` → `apps/python/large_data_camera/large_data_camera_logic.py` | Template file | ✅ Exists |
| Copy `requirements.txt.template` → `apps/python/large_data_camera/requirements.txt` | Template file | ✅ Exists |
| Copy `run.sh.template` → `apps/python/large_data_camera/run.sh` | Template file | ✅ Exists |
| Substitute `{{PROCESS_NAME}}` → `large_data_camera` | Agent logic | ⚠️ Documented but not coded |
| Substitute `{{IMPORTS}}` → import statements for Image type | Agent logic | ⚠️ |
| Substitute `{{READER_SETUP}}` → DataReader code | Blueprint reference | ❌ **GAP R4-2** |
| Substitute `{{WRITER_SETUP}}` → DataWriter code | Blueprint reference | ❌ Same |
| Substitute `{{SUBSCRIBER_COROUTINES}}` → async reader coroutine | Blueprint reference | ❌ Same |
| Substitute `{{PUBLISHER_COROUTINES}}` → async writer coroutine | Blueprint reference | ❌ Same |
| Substitute `{{QOS_PROFILE}}` → `DPLibrary::LargeDataSHMEMParticipant` | Design YAML | ⚠️ Schema gap |

**Gap R4-1: No `python/manifest.yaml`.** Without the manifest, the agent
doesn't know which template files to copy or what substitution variables to
populate. The scaffold templates exist and are well-designed, but the
"instruction set" for how to use them is missing.

**Gap R4-2: No blueprint code for large_data/python/.** The template has
placeholder slots (`{{READER_SETUP}}`, `{{PUBLISHER_COROUTINES}}`, etc.) that
need to be filled with pattern-specific code. The
`system_templates/blueprints/large_data/python/` directory is empty. Without
blueprints, the agent must generate code from scratch using only its training
knowledge of the RTI Python API.

This is the **most significant gap** for this use case. The existing
`apps/python/large_data_app/large_data_app.py` shows the correct pattern but
it's a finished monolithic file, not a decomposed blueprint. The agent needs
reference code broken into the template slots:
- `reader_callback.py.template` → async for loop + take_data_async
- `writer_periodic.py.template` → async publish loop with sample construction

**Gap R4-3: Import path generation.** The Python template needs
`{{IMPORTS}}` to be:
```python
from python_gen.ExampleTypes import example_types
```
The mapping from IDL module path → Python import statement is not documented
anywhere. The agent must know:
- IDL module `example_types` → Python package `python_gen.ExampleTypes`
- Class access: `example_types.Image`
- The build directory: `dds/datamodel` or `build/dds/python_gen/`

The existing `large_data_app.py` shows the pattern but it's never codified as a
rule for the agent.

**Recommendation:** Add to docs/01 (Rules) or a new section:

```
PYTHON IMPORT RULES:
- sys.path insert: PROJECT_ROOT / "dds" / "datamodel"  (for pre-built)
  OR: PROJECT_ROOT / "build" / "dds" / "python_gen"  (for build-time)
- Import statement: from python_gen.<IdlFileName> import <module_name>
- Example: ExampleTypes.idl with module example_types
  → from python_gen.ExampleTypes import example_types
  → Access: example_types.Image
```

#### Step 2: rtiddsgen

| Action | Artifact Needed | Exists? |
|--------|-----------------|---------|
| Run `rtiddsgen -language Python -d dds/build/python_gen/ dds/datamodel/idl/ExampleTypes.idl` | rtiddsgen binary | ✅ (Connext installed) |

No gaps — types already exist, rtiddsgen is a standard command.

But wait: for "Select Existing" type (`example_types::Image`), the codegen
was already done during a previous build. **Gap R4-4: The agent needs to know
whether to re-run rtiddsgen or skip it.** If the type was used by a prior
process, the generated code already exists. Running rtiddsgen again with
`-replace` is safe but unnecessary. The manifest should track "already
generated" IDL files.

#### Step 3: QoS Assembly

| Action | Artifact Needed | Exists? |
|--------|-----------------|---------|
| Verify `LargeDataSHMEMQoS` exists in DDS_QOS_PROFILES.xml | QoS XML file | ✅ |
| Verify `LargeDataSHMEMParticipant` exists | QoS XML file | ✅ |
| No assembly needed — profiles already in monolithic XML | – | ✅ |

For this use case, the existing monolithic QoS XML works. The QoS fragment
system (`qos_templates/*.xml.fragment`) would be needed if a user wanted a
custom pattern or the system needed to compose QoS dynamically. But for all
5 data patterns + system patterns, the profiles are already defined.

**Gap R4-5: QoS fragment vs monolithic ambiguity.** The architecture describes
QoS fragments that get merged. But `DDS_QOS_PROFILES.xml` already has
everything. When does the fragment system apply?

**Recommendation:** Clarify the QoS strategy:
- **Option A (simpler):** Fragments are *source of truth* — `DDS_QOS_PROFILES.xml`
  is generated FROM fragments on every build. Ship fragments, generate monolith.
- **Option B (current reality):** The monolithic file IS the source of truth.
  Fragments are for the agent's reference only (to understand what settings each
  pattern needs). No assembly step needed.
- **Recommendation: Option B for now,** document it. The monolithic QoS file
  works. The "assembly" step in Phase 4 becomes "verify the needed profile
  exists in QoS XML; if it doesn't, warn the user."

#### Step 4: App Code Generation

| Action | Artifact Needed | Exists? |
|--------|-----------------|---------|
| Generate filled `large_data_camera.py` | `builder.prompt.md` | ❌ **GAP R4-6** |
| Generate filled `large_data_camera_logic.py` | `builder.prompt.md` | ❌ Same |
| Reference: blueprint for large_data/python | Blueprint templates | ❌ **GAP R4-2** (repeat) |
| Reference: existing large_data_app.py | Example app | ✅ |

**Gap R4-6: No `builder.prompt.md`.** This is the core code generation
sub-prompt. It needs to:
1. Read the PROCESS_DESIGN.yaml
2. Read the scaffold templates
3. Read blueprint references for the pattern
4. Perform `{{VARIABLE}}` substitution
5. Generate the logic file stubs
6. Enforce clean architecture (no DDS in logic layer)

Without it, the agent generates code purely from general knowledge. Given we
have a working reference app (`large_data_app.py`), a skilled agent could
produce reasonable output. But the prompt provides consistency and correctness
guarantees.

**What the generated Python code should look like:**

```python
# large_data_camera.py (from template with substitutions)
import rti.connextdds as dds
import rti.asyncio
from python_gen.ExampleTypes import example_types
from large_data_camera_logic import LargeDataCameraLogic

async def subscribe_image(reader, logic):
    async for data in reader.take_data_async():
        logic.on_image_received(data)

async def publish_image(writer, logic):
    while not shutdown_event.is_set():
        sample = logic.compute_image()
        if sample is not None:
            writer.write(sample)
        await asyncio.sleep(1.0)  # 1 Hz

async def run(domain_id, qos_file):
    qos_provider = dds.QosProvider(qos_file)
    participant_qos = qos_provider.participant_qos_from_profile(
        "DPLibrary::LargeDataSHMEMParticipant")
    participant = dds.DomainParticipant(domain_id, participant_qos)
    # ... reader/writer setup with LargeDataSHMEMQoS
```

```python
# large_data_camera_logic.py (from template with substitutions)
class LargeDataCameraLogic:
    def on_image_received(self, data):
        print(f"Image received: {data.image_id}, {len(data.data)} bytes")

    def compute_image(self):
        sample = example_types.Image()
        sample.image_id = f"img_{self._count:06d}"
        sample.width = 640
        sample.height = 480
        sample.format = "RGB"
        sample.data = [0] * (640 * 480 * 3)
        self._count += 1
        return sample
```

#### Step 5: Test Generation

| Action | Artifact Needed | Exists? |
|--------|-----------------|---------|
| Generate `test_large_data_camera.py` | `tester.prompt.md` | ❌ **GAP R4-7** |
| Generate `conftest.py` | `tests/conftest.py.template` | ❌ **GAP R4-8** |
| Test fixtures: DomainParticipant, isolated domain | Test helper templates | ❌ Same |

**Gap R4-7: No `tester.prompt.md`.** Tests need pytest fixtures for clean DDS
participant lifecycle, domain isolation (domain_id=100), subprocess launch for
integration tests, and timeout management. None of this is templated.

**Gap R4-8: No test infrastructure.** No `conftest.py.template`, no test
helpers directory, no standard fixtures. The architecture docs describe tests
but the scaffolding doesn't include test file templates.

#### Steps 6-7: Build & Run Tests

| Action | Artifact Needed | Exists? |
|--------|-----------------|---------|
| No build step for Python (it's interpreted) | – | ✅ |
| Run `pytest tests/ -v` | pytest installed in venv | ✅ |
| Verify tests pass | Test files from Step 5 | ❌ (depends on R4-7) |

---

### Use Case 1: Gap Summary

| Gap ID | Severity | Description | Blocks |
|--------|----------|-------------|--------|
| R0-1 | LOW | No bootstrap/reference_manifest.yaml | First-time setup |
| R0-2 | MEDIUM | Python + Wrapper Class manifest routing unclear | Phase 4 scaffold |
| R2-1 | LOW | No system_manifest.yaml (no system patterns → low impact here) | Phase 2 automation |
| **R3-1** | MEDIUM | No datamodel.prompt.md | Type definition gate |
| **R3-2** | MEDIUM | No patterns.prompt.md | Pattern auto-resolve |
| **R3-4** | **HIGH** | No participant_qos_profile in design YAML | SHMEM will fail for large data |
| R3-5 | MEDIUM | No tester.prompt.md | Test auto-proposal |
| **R4-1** | **HIGH** | No python/manifest.yaml | Scaffold step cannot execute |
| **R4-2** | **HIGH** | No large_data/python blueprint code | Agent must improvise all code |
| R4-3 | MEDIUM | Python import path rules undocumented | Wrong imports in generated code |
| R4-5 | LOW | QoS fragment vs monolithic strategy unclear | Confusion in Phase 4 Step 3 |
| **R4-6** | **HIGH** | No builder.prompt.md | Code generation has no guide |
| R4-7 | MEDIUM | No tester.prompt.md | Test generation unguided |
| R4-8 | MEDIUM | No test infrastructure templates | No conftest.py, no fixtures |

**Can the use case succeed today?** Partially. An experienced agent with access
to the existing `large_data_app.py` as reference could produce a working app,
but it would require improvisation at every Phase 4 step. The workflow would
not be reproducible or consistent across sessions.

---

## Use Case 2: "I want to integrate Foxglove with large images"

README link: *I want maximum performance with zero-copy transfer* +
*I want to downsample high-frequency data for GUIs*

This use case is more complex: a C++ publisher sends high-rate FlatData images
via zero-copy SHMEM, while a Python subscriber downsamples for visualization
(Foxglove or any GUI tool). This exercises **cross-language**, **large data**,
**zero-copy**, and **downsampling** patterns.

### What the user actually needs

1. **C++ image publisher** — publishes `FinalFlatImage` at 10 Hz using zero-copy
   (`@transfer_mode(SHMEM_REF)`)
2. **Python visualization subscriber** — receives images at 1 Hz (downsampled
   via `TIME_BASED_FILTER`) and feeds them to a visualization tool
3. **Shared IDL** — both processes use the same `FinalFlatImage` type
4. **QoS coordination** — publisher uses `LargeDataSHMEMZCQoS` (zero-copy),
   subscriber uses `DownsampledLargeDataQoS` (time-based filter)

### Phase 0 — Project Init

| Step | Agent Action | Gap? |
|------|-------------|------|
| Framework | Wrapper Class | ✅ |
| API | **Both: modern_cpp + python** (`modern_cpp_python`) | ⚠️ **GAP F0-1** |

**Gap F0-1: "Both" API mode is under-specified.** The `project.yaml.example`
lists `modern_cpp_python` as a valid API option with derived fields:
`rtiddsgen_language: "C++11 and Python"`, `build_system: "cmake+pip"`,
`app_dir: "apps/cxx11/ and apps/python/"`. But:
- No manifest handles dual-language generation
- `rtiddsgen` must be run twice (once for C++11, once for Python)
- Build integration needs both CMake and pip
- The scaffold step must know which language each process uses

**Recommendation:** Each process in the design should declare its own language:

```yaml
process:
  name: image_publisher
  language: modern_cpp       # ← NEW FIELD, overrides project default
```

When `project.api: modern_cpp_python`, the per-process `language` field
becomes required. This lets a single project contain both C++ and Python
processes.

---

### Phase 1 — System Design

| Step | Agent Action | Gap? |
|------|-------------|------|
| Domain ID | 0 (default) | ✅ |
| Patterns | None needed for this use case | ✅ |

---

### Phase 2 — System Implementation

Same as Use Case 1 — minimal. Just verify directories exist.

---

### Phase 3 — Process Design (Process 1: image_publisher)

#### Step 1: Identity

```yaml
process:
  name: image_publisher
  language: modern_cpp        # GAP F0-1 — this field needed
  transports: [SHMEM]
  participant_qos_profile: "DPLibrary::LargeDataSHMEMParticipant"  # GAP R3-4
```

#### Step 2: Define I/O

**Output: FinalFlatImage images at 10 Hz**

| Step | Agent Action | Gap? |
|------|-------------|------|
| Type gate | "Select Existing" → finds `example_types::FinalFlatImage` | ❌ same as R3-1 |
| Pattern auto-resolve | `@final @language_binding(FLAT_DATA)` → Large Data Option 2 (Zero-Copy) | ✅ Rule exists in docs/07 |
| QoS profile | `DataPatternsLibrary::LargeDataSHMEMZCQoS` | ✅ Exists in QoS XML |
| Rate | 10 Hz | ✅ |

**Observation:** The auto-resolve rule for FlatData → zero-copy is well
documented. However, the agent needs to detect the IDL annotations
(`@language_binding(FLAT_DATA)`, `@transfer_mode(SHMEM_REF)`) to trigger this.

**Gap F3-1: IDL annotation detection not codified as agent rule.** The agent
needs to parse IDL files to find these annotations. Currently, the patterns
prompt (which doesn't exist) would need to know: "scan the selected type's IDL
for `@language_binding(FLAT_DATA)` — if found, auto-select Large Data option
2."

**Gap F3-2: Zero-copy has C++ only constraint.** `FinalFlatImage` with
`@transfer_mode(SHMEM_REF)` is a zero-copy type that only works in C++14+
with FlatData APIs. Python cannot do true zero-copy — it must use regular
serialized SHMEM. The agent should:
1. For C++ process: use `LargeDataSHMEMZCQoS` (zero-copy)
2. For Python process: use `LargeDataSHMEMQoS` (regular SHMEM, no zero-copy)

This cross-language QoS asymmetry is **not documented anywhere**. The current
QoS profile system doesn't account for per-language constraints.

**Recommendation:** Add to docs/07 (Patterns Reference):

```
LANGUAGE CONSTRAINTS FOR LARGE DATA:
- Zero-Copy (Option 2): C++ only. Requires @final @language_binding(FLAT_DATA).
  Python/Java cannot use zero-copy — fall back to Option 1 (SHMEM) or
  use a non-FlatData equivalent type.
- If a Python process subscribes to a type published with zero-copy by C++,
  the Python reader uses standard SHMEM QoS. DDS handles the serialization
  mismatch transparently (FlatData is still XCDR2 on the wire).
```

#### Step 2 (continued): Define Input — Command (optional for control)

User might also want a Command input to start/stop image capture. This is
straightforward and well-supported by the workflow.

---

### Phase 3 — Process Design (Process 2: image_viewer)

#### Step 1: Identity

```yaml
process:
  name: image_viewer
  language: python            # GAP F0-1 — field needed
  transports: [SHMEM]
  participant_qos_profile: "DPLibrary::LargeDataSHMEMParticipant"
```

#### Step 2: Define I/O

**Input: FinalFlatImage downsampled to 1 Hz**

| Step | Agent Action | Gap? |
|------|-------------|------|
| Type gate | "Select Existing" → `example_types::FinalFlatImage` | ✅ |
| Pattern | Large Data — but which option? | ⚠️ **GAP F3-3** |
| QoS profile | Need TIME_BASED_FILTER on top of Large Data | ⚠️ **GAP F3-4** |

**Gap F3-3: Downsampling is not a data pattern — it's a QoS modifier.** The
current pattern catalog has 5 data patterns: Event, Status, Command, Parameter,
Large Data. Downsampling (via `TIME_BASED_FILTER`) is described in the Status
pattern (Option 2: Downsampled) but NOT in the Large Data pattern.

A user who wants "large images at 1 Hz from a 10 Hz publisher" needs:
- Large Data transport settings (SHMEM, large buffer sizes)
- PLUS Time-Based Filter QoS (minimum_separation = 1s)

These are two orthogonal concerns. The current pattern system doesn't support
composition of patterns on a single I/O.

**Gap F3-4: No composite QoS profile for Large Data + Downsampled.** The
existing QoS XML has:
- `DataPatternsLibrary::LargeDataSHMEMQoS` — SHMEM transport, large buffers
- `DataPatternsLibrary::DownsampledStatusQoS` (if it existed) — TIME_BASED_FILTER

But there's no `LargeDataSHMEMDownsampledQoS` profile. The agent would need to
either:
- Create a new composite QoS profile (assembly)
- Or set TIME_BASED_FILTER programmatically in code

**Recommendation:** Add a "QoS modifier" concept to the design:

```yaml
inputs:
  - name: image_input
    topic: FinalFlatImageTopic
    type: example_types::FinalFlatImage
    pattern: large_data
    pattern_option: 1           # SHMEM (not zero-copy — Python can't do ZC)
    qos_profile: "DataPatternsLibrary::LargeDataSHMEMQoS"
    qos_modifiers:              # ← NEW FIELD
      - type: time_based_filter
        minimum_separation_ms: 1000
    callbacks: [data_available]
```

Or alternatively, allow stacking a "downsample" modifier:
```yaml
    pattern: large_data
    pattern_option: 1
    downsample_hz: 1            # ← simpler, single field
```

The agent would then either find an existing composite profile or generate one.

**Gap F3-5: Cross-language type compatibility not validated.** The C++
publisher uses `FinalFlatImage` with `@language_binding(FLAT_DATA)`. The Python
subscriber must use a compatible type. In RTI Connext, FlatData types are
wire-compatible with regular types (XCDR2 encoding). But:
- The Python codegen (`rtiddsgen -language Python`) may or may not generate
  code for `@language_binding(FLAT_DATA)` types
- The `@transfer_mode(SHMEM_REF)` annotation is publisher-side only
- The subscriber just sees a regular XCDR2 sample

The agent needs rules for cross-language type handling:
- If type has `@language_binding(FLAT_DATA)` and target is Python:
  → Use the type WITHOUT the annotation for Python codegen
  → Or use the regular `Image` type (non-FlatData equivalent) on the Python side
  → Both must produce compatible wire encoding

**Recommendation:** For the Foxglove use case specifically, the simpler path
is:
1. C++ publisher: `FinalFlatImage` with zero-copy
2. Python subscriber: subscribes to same topic using regular `Image` type
   (not FlatData), with standard SHMEM QoS
3. Add an IDL rule that FlatData types have a non-FlatData "twin" for
   cross-language readers

Or document that Python can subscribe to FlatData topics using the same type
name — just with different code generation flags. This is actually how RTI
Connext works (the wire format is the same), but it's not documented for the
agent.

---

### Phase 4 — Process Implementation (image_publisher, C++)

#### Step 1: Scaffold

| Action | Artifact Needed | Exists? |
|--------|-----------------|---------|
| Read manifest | `system_templates/wrapper_class/manifest.yaml` | ❌ **Same as R4-1** |
| Copy templates | `app_main.cxx.template`, `process_logic.hpp/cxx.template`, etc. | ✅ Templates exist |
| Substitute `{{INCLUDES}}` | Need FlatData-specific includes: `#include "ExampleTypes/ExampleTypes.hpp"`, `#include <rti/flat/FlatData.hpp>` | ⚠️ **GAP F4-1** |

**Gap F4-1: FlatData-specific code generation.** Zero-copy FlatData apps use
significantly different APIs than regular DDS apps:
- Builder pattern: `FinalFlatImageBuilder builder = writer.get_loan();`
- `builder.add_image_id(...)` instead of `sample.image_id = ...`
- `writer.write(*builder.finish())` instead of `writer.write(sample)`
- Loan management: `writer.get_loan()` + ownership semantics

The current scaffold templates (`app_main.cxx.template`) use standard
`DDSWriterSetup<T>::write()` which doesn't handle FlatData loans. The agent
needs a FlatData-specific code path.

**Gap F4-2: No FlatData blueprint.** `system_templates/blueprints/large_data/cxx11/`
is empty. Even for regular large data, there's no blueprint. For FlatData
zero-copy, the blueprint is essential because the API is fundamentally
different.

The reference implementation exists at
`apps/cxx11/fixed_image_flat_zc/fixed_image_flat_zc.cxx` — this shows exactly
how to use FlatData builders and loans. But it's a finished app, not a
decomposed template.

#### Step 4: App Code Generation

**Gap F4-3: Wrapper class headers don't support FlatData.** The
`DDSWriterSetup<T>` wrapper provides `write(const T& sample)`. For FlatData,
you need `get_loan()` which returns a `WriteSample<T>`. Either:
1. Add FlatData support to `DDSWriterSetup` (e.g., `get_loan()` method)
2. Or bypass the wrapper for FlatData types and use raw DDS API
3. Or add a `DDSFlatDataWriterSetup<T>` wrapper variant

The builder prompt needs to know which path to take based on the type
annotations.

---

### Phase 4 — Process Implementation (image_viewer, Python)

Same gaps as Use Case 1 Python (R4-1 through R4-8), plus:

**Gap F4-4: Foxglove/visualization integration not addressed.** The
architecture has no concept of "output to external tool." The workflow assumes
DDS is the only output. For Foxglove integration, the Python app needs to:
- Convert DDS Image samples to a format Foxglove understands (e.g., protobuf,
  JSON, or WebSocket frames)
- Or use Foxglove's DDS bridge (which subscribes directly to DDS topics)
- Or use RTI Recording Service → MCAP conversion → Foxglove file playback

The current downsampled_reader example demonstrates the subscription side
perfectly but says nothing about visualization tool integration.

**Recommendation:** The existing `downsampled_reader/` app is the perfect
reference for approach 2 (Foxglove DDS bridge). The QoS TIME_BASED_FILTER
approach works for any subscriber, including Foxglove. Add to docs or README:

```
For Foxglove integration:
Option A: Use Foxglove's DDS extension to subscribe directly to DDS topics
Option B: Run a Python bridge that subscribes to DDS and forwards via WebSocket
Option C: Record with RTI Recording Service, convert to MCAP, open in Foxglove
```

---

### Use Case 2: Gap Summary

| Gap ID | Severity | Description | Blocks |
|--------|----------|-------------|--------|
| **F0-1** | **HIGH** | `modern_cpp_python` mode needs per-process language field | Multi-language projects |
| R3-4 | HIGH | No participant_qos_profile field (same as UC1) | SHMEM buffer sizing |
| **F3-1** | MEDIUM | IDL annotation detection not codified | Auto-resolve for FlatData |
| **F3-2** | **HIGH** | Zero-copy is C++ only — no cross-language constraint documented | Python subscriber QoS mismatch |
| **F3-3** | **HIGH** | Downsampling not composable with Large Data pattern | Cannot express "large data at 1 Hz" |
| **F3-4** | MEDIUM | No composite QoS profile for Large Data + Downsampled | Missing QoS profile |
| **F3-5** | MEDIUM | Cross-language FlatData type compatibility undocumented | Python + FlatData mismatch |
| F4-1 | MEDIUM | FlatData includes/code path not in templates | C++ zero-copy codegen |
| **F4-2** | **HIGH** | No FlatData/large_data blueprint code | Agent must improvise ZC code |
| F4-3 | MEDIUM | Wrapper classes don't support FlatData loans | DDSWriterSetup gap |
| F4-4 | LOW | No Foxglove/visualization integration guidance | External tool gap |

---

## Cross-Cutting Gaps (Both Use Cases)

### Schema Gaps

| # | Gap | Recommendation | Impact |
|---|-----|----------------|--------|
| S1 | **No `participant_qos_profile`** in PROCESS_DESIGN.yaml | Add field + auto-derive rule | HIGH — SHMEM will fail for large data |
| S2 | **No per-process `language` field** | Add when `project.api` is dual-language | HIGH — blocks multi-language projects |
| S3 | **No `qos_modifiers` or `downsample_hz`** on I/O entries | Add composable QoS modifier concept | HIGH — can't express downsampled subscription |
| S4 | Pattern system doesn't compose (Large Data + Downsample) | Add modifier layer or sub-options | MEDIUM — workaround is manual QoS |

### Template Gaps

| # | Gap | What's Needed | Roadmap Phase |
|---|-----|---------------|---------------|
| T1 | No manifest.yaml files (3 framework manifests + system) | File list + substitution rules | R1 |
| T2 | No QoS fragment files (12 patterns) | Extract from DDS_QOS_PROFILES.xml or document as reference-only | R2 |
| T3 | No blueprint code (5 patterns × 2 languages = 10 dirs) | At minimum: large_data/python, large_data/cxx11 | R4 |
| T4 | No FlatData-specific blueprint | New: large_data_zc/cxx11/ with builder pattern | R4 |
| T5 | No test infrastructure templates | conftest.py.template, test_helpers/ | R5 |

### Prompt Gaps

| # | Gap | What's Needed | Roadmap Phase |
|---|-----|---------------|---------------|
| P1 | No datamodel.prompt.md | Type walkthrough, IDL validation, existing type scanner | R6 |
| P2 | No patterns.prompt.md | Auto-resolve engine, QoS mapping, constraint rules | R6 |
| P3 | No builder.prompt.md | Code generation with clean architecture, template substitution | R6 |
| P4 | No tester.prompt.md | Test auto-proposal, pytest fixtures, integration patterns | R6 |
| P5 | rti_dev.prompt.md is basic | Full orchestrator with Phase 3-4 loops, menu system | R7 |

### Process/Documentation Gaps

| # | Gap | Where to Fix |
|---|-----|-------------|
| D1 | Python import path rules undocumented | docs/01_rules.md (new PYTHON-* rules) |
| D2 | FlatData cross-language constraints undocumented | docs/07_patterns_reference.md |
| D3 | QoS fragment vs monolithic strategy unclear | docs/04 or docs/09 |
| D4 | Manifest routing for (framework × api) combinations | docs/09_repository_structure.md |
| D5 | Foxglove/external visualization integration not addressed | README or new doc |
| D6 | Python `sys.path` conventions vary between existing apps | Standardize in docs/01_rules.md |

---

## Priority-Ordered Action Items

Based on blocking severity across both use cases:

### Must-Fix Before Any Use Case Works (Blocking)

1. **S1: Add `participant_qos_profile` to PROCESS_DESIGN.yaml schema** — Without
   this, any large data process fails (SHMEM buffers too small). Add field to
   docs/05 schema + both `.yaml.example` files. Add auto-derive rule to
   docs/08.

2. **T1: Create manifest.yaml files** — At minimum create
   `system_templates/python/manifest.yaml` (for UC1) and
   `system_templates/wrapper_class/manifest.yaml` (for UC2 C++ process). These
   gate Phase 4 Step 1.

3. **P3: Create `builder.prompt.md`** — Even a minimal version that reads the
   design YAML and performs template substitution would unblock code generation.
   Reference the existing example apps as blueprints.

### Should-Fix for Consistent Results

4. **S2: Add per-process `language` field** for multi-language projects
5. **S3: Add `qos_modifiers` or `downsample_hz`** to I/O schema
6. **T3: Create at least `large_data/python/` and `large_data/cxx11/` blueprints**
   by extracting from existing example apps
7. **P1-P2: Create `datamodel.prompt.md` and `patterns.prompt.md`**
8. **D1-D2: Document Python import rules and FlatData cross-language constraints**

### Nice-to-Have for Completeness

9. T2: QoS fragments (or clarify monolithic strategy)
10. T4: FlatData zero-copy blueprint
11. T5: Test infrastructure
12. P4: tester.prompt.md
13. D5: Foxglove integration guide
14. P5: Full orchestrator rewrite

---

## Conclusion

The architecture documentation (13 docs) is thorough and well-designed. The
five-phase workflow, pattern system, and clean architecture rules are sound. The
scaffold templates exist and are well-structured with proper substitution
variables.

**The primary gap is the "executable" layer** — the manifest files, blueprint
code, and sub-prompts that turn the architecture into a running system. The
documentation describes *what* to build; the templates describe *where* to put
it; but the manifests (how to assemble) and blueprints (what code to generate)
are missing.

For the two README use cases tested:
- **UC1 (Python SHMEM large data):** ~70% of the path works. The main blockers
  are `python/manifest.yaml`, `builder.prompt.md`, and the
  `participant_qos_profile` schema gap.
- **UC2 (Foxglove + C++ zero-copy + Python viewer):** ~50% of the path works.
  Additional blockers: multi-language support, FlatData handling, pattern
  composition (Large Data + Downsample), and cross-language type rules.

The existing example apps (`large_data_app/`, `fixed_image_flat_zc/`,
`downsampled_reader/`) are excellent reference implementations that could be
decomposed into blueprints — they demonstrate exactly what the generated code
should look like.
