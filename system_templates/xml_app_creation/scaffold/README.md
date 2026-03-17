# XML App Creation Scaffold Templates

These parameterized templates generate DDS processes using the **XML App Creation**
pattern, where DDS entities (participants, publishers, subscribers, writers, readers)
are defined declaratively in XML rather than programmatically in code.

Based on the [RTI MedTech Reference Architecture](https://github.com/rticommunity/rticonnextdds-medtech-reference-architecture).

## Files

| Template | Generated As | Purpose |
|---|---|---|
| `DomainLibrary.xml.template` | `system_arch/xml_app_creation/DomainLibrary.xml` | Type registrations & topic definitions |
| `ParticipantLibrary.xml.template` | `system_arch/xml_app_creation/ParticipantLibrary.xml` | Participant, publisher, subscriber config |
| `CMakeLists.txt.template` | `apps/cxx11/<process>/CMakeLists.txt` | Build configuration |
| `app_main.cxx.template` | `apps/cxx11/<process>/main.cxx` | Entry point — creates participant from config |
| `callbacks.hpp.template` | `apps/cxx11/<process>/<name>_callbacks.hpp` | Callback interface (logic layer) |
| `callbacks.cxx.template` | `apps/cxx11/<process>/<name>_callbacks.cxx` | Callback implementation |
| `run.sh.template` | `apps/cxx11/<process>/run.sh` | Launch script with XML config paths |

## Naming Conventions

Following the MedTech Reference Architecture:

| Entity | Prefix | Example |
|---|---|---|
| Domain Participant | `dp/` | `dp/GpsTracker` |
| Publisher | `p/` | `p/publisher` |
| Subscriber | `s/` | `s/subscriber` |
| DataWriter | `dw/` | `dw/PositionOutput` |
| DataReader | `dr/` | `dr/CommandInput` |
| Topic | `t/` | `t/Position` |

## How It Works

1. **DomainLibrary.xml** defines the domain, registers IDL types, and declares topics
2. **ParticipantLibrary.xml** defines participants with their publishers/subscribers/writers/readers
3. **main.cxx** calls `create_participant_from_config()` to instantiate everything from XML
4. **Entity lookup** finds writers/readers by their XML names (e.g., `"p/publisher::dw/PositionOutput"`)
5. **Callbacks** handle data processing in the logic layer

## Substitution Variables

### XML Configuration
- `{{DOMAIN_LIBRARY_NAME}}` — domain_library element name
- `{{DOMAIN_NAME}}` — domain element name  
- `{{PARTICIPANT_LIBRARY_NAME}}` — domain_participant_library name
- `{{DOMAIN_REF}}` — reference linking participant to domain
- `{{TYPE_REGISTRATIONS}}` — `<register_type>` elements
- `{{TOPIC_DEFINITIONS}}` — `<topic>` elements
- `{{PARTICIPANTS}}` — `<domain_participant>` elements with full entity tree

### C++ Code
- `{{WRITER_LOOKUPS}}` — `rti::pub::find_datawriter_by_name<>()` calls
- `{{READER_LOOKUPS}}` — `rti::sub::find_datareader_by_name<>()` calls
- `{{LISTENER_SETUP}}` — listener registration for DataReaders
