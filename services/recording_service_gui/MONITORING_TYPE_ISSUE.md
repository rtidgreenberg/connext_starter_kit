# Issue: Cannot Deserialize Recording Service Monitoring Data in Python

## Environment

| Component | Version |
|---|---|
| RTI Connext DDS | 7.3.1 |
| RTI Recording Service | 7.3.1 |
| rti.connext (Python) | 7.3.1 |
| rtiddsgen | 4.3.1 |
| Python | 3.8.10 |
| OS | Ubuntu 20.04.6 LTS (x86_64, kernel 5.15.0) |

## Problem Statement

We cannot subscribe to RTI Recording Service monitoring topics
(`rti/service/monitoring/config`, `event`, `periodic`) from Python using
**any** of the three supported type approaches.  The Recording Service C++
publisher is confirmed working — `rtiddsspy` sees the data on the wire — but
the Python reader either fails to match or fails to deserialize.

## Approaches Tried

### Approach 1 — Python Generated Types (`rtiddsgen -language Python`)

**Steps:**
1. Copied IDL files from `$NDDSHOME/resource/idl/` (ServiceCommon.idl,
   ServiceMonitoring.idl, RecordingServiceMonitoring.idl,
   RoutingServiceMonitoring.idl).
2. Ran `rtiddsgen -language Python` to generate Python type support.
3. Created typed `Topic` and `DataReader` in Python.

**Result:** 0 matched publications.  The XTypes type hash computed from the
Python-generated type support does not match the hash advertised by the C++
Recording Service.  Endpoints never match; no data is received.

---

### Approach 2 — DynamicData from Discovered Types (Runtime Discovery)

**Steps:**
1. Created a `DomainParticipant` in disabled state
   (`entity_factory.autoenable_created_entities = False`).
2. Attached a `PublicationBuiltinTopicData.DataReaderListener` to
   `participant.publication_reader`.
3. Enabled the participant; listener discovered all 3 monitoring writers with
   their `DynamicType` and `type_name`.
4. Called `participant.register_type(pub_type_name, discovered_dynamic_type)` to
   register the discovered type under the publisher's type_name.
5. Created `DynamicData.Topic(participant, topic_name, pub_type_name, TopicQos())`
   using the registered type_name.
6. Created `DynamicData.DataReader` with QoS matching the discovered writer.

**Observations:**
- Discovery succeeds — all 3 types are found:
  - `type_name='RTI::Service::Monitoring::Config'`,
    `DynamicType.name='RTI::RecordingService::Monitoring::Config'`
  - (same pattern for Event and Periodic)
- The publisher registers the topic with the generic service type_name
  (`RTI::Service::Monitoring::Config`), but the DynamicType's fully-qualified
  name is the concrete Recording-Service-specific version
  (`RTI::RecordingService::Monitoring::Config`).
- Even with `register_type(pub_type_name, dtype)`, even with
  `force_type_validation=False`, even with
  `type_code_max_serialized_length=0` and `type_object_max_serialized_length=0`
  on the participant — 0 matched publications.

**Result:** 0 matched publications.  The XTypes hash derived from the
`DynamicType` (which has the RecordingService-specific FQN) does not match the
hash the C++ publisher advertises for the generic Service-level type_name.

---

### Approach 3 — DynamicData from XML Types (`rtiddsgen -convertToXml`)

**Steps:**
1. Copied IDL files from `$NDDSHOME/resource/idl/` (same version 7.3.1).
2. Ran `rtiddsgen -convertToXml` for each IDL file.
3. Loaded types via `dds.QosProvider("ServiceMonitoring.xml")`.
4. Created `DynamicData.Topic` and `DynamicData.DataReader`.

**Observations:**
- **Types load correctly** — `provider.type("RTI::Service::Monitoring::Config")`
  returns a valid `DynamicType` with name `RTI::Service::Monitoring::Config`.
- **Matching succeeds** — `matched_publications = 1`.
- **Deserialization fails** with:
  ```
  RTIXCdrInterpreter_processUnknownDisc:RTI::Service::Monitoring::ConfigUnion:disc
  deserialization error. Unknown union discriminator value 20000
  ```

**Root Cause:**  
The generated XML files contain **symbolic enum references** in
`caseDiscriminator` values that the C-level XCDR deserializer cannot resolve at
runtime.

Example from `ServiceMonitoring.xml`:
```xml
<caseDiscriminator value="(RTI::Service::Monitoring::RECORDING_SERVICE)"/>
```

The Python `QosProvider` correctly resolves these to integer labels at the
DynamicType level (verified: `recording_service: labels=[20000]`), but the
underlying C XCDR interpreter does not use the resolved DynamicType labels — it
uses its own internal TypeCode representation, and that representation does not
resolve symbolic references.

**This is the closest approach** — it matches, it receives data on the wire, but
deserialization fails at the C layer.

**Affected files and symbolic reference counts (freshly generated from 7.3.1 IDL):**

| File | Symbolic Refs |
|---|---|
| ServiceCommon.xml | 3 (ResourceKind enum base values) |
| ServiceMonitoring.xml | 33 (caseDiscriminator values) |
| RecordingServiceMonitoring.xml | 12 (caseDiscriminator values) |
| RoutingServiceMonitoring.xml | 21 (caseDiscriminator values) |
| ServiceAdmin.xml | 2 (const references) |
| RecordingServiceTypes.xml | 4 (caseDiscriminator values) |

---

## Summary

| Approach | Matching | Deserialization | Blocker |
|---|---|---|---|
| Python generated types | **0 matched** | N/A | XTypes hash mismatch |
| Discovery-based DynamicType | **0 matched** | N/A | type_name FQN mismatch (generic vs concrete) |
| XML DynamicData (`-convertToXml`) | **1 matched** | **Fails** | XCDR can't resolve symbolic enum caseDiscriminator |

## Reproducer

See `test/reproducer_monitoring_xml.py` — a self-contained script that
demonstrates Approach 3 (the closest to working).  Requires a running Recording
Service on domain 0.

### To run:

```bash
# Terminal 1 — start Recording Service
cd services/
rtirecordingservice -cfgFile "recording_service_config.xml;../dds/qos/DDS_QOS_PROFILES.xml" \
  -cfgName deploy -DDOMAIN_ID=0 -DADMIN_DOMAIN_ID=0

# Terminal 2 — run reproducer
cd services/recording_service_gui/
source ../../connext_dds_env/bin/activate
python3 test/reproducer_monitoring_xml.py
```

### Expected

```
Matched: 1
DATA RECEIVED: [sample content]
```

### Actual

```
Matched: 1
ERROR RTIXCdrInterpreter_processUnknownDisc:...ConfigUnion:disc
  deserialization error. Unknown union discriminator value 20000
No valid samples received (deserialization failed)
```

## Potential Fix

Replace all symbolic `caseDiscriminator` and `enumerator` values in the
generated XML files with their literal integer equivalents.  The mapping
(from `ResourceKind` enum in the IDL):

```
ROUTING_SERVICE       = 10000    ROUTING_DOMAIN_ROUTE  = 10001
ROUTING_SESSION       = 10002    ROUTING_AUTO_ROUTE    = 10003
ROUTING_ROUTE         = 10004    ROUTING_INPUT         = 10005
ROUTING_OUTPUT        = 10006
RECORDING_SERVICE     = 20000    RECORDING_SESSION     = 20001
RECORDING_TOPIC_GROUP = 20002    RECORDING_TOPIC       = 20003
CDS_SERVICE           = 30000    CDS_FORWARDER         = 30001
CDS_DATABASE          = 30002    CDS_RECEIVER          = 30003
CDS_SENDER            = 30004
```

This is a workaround for what appears to be a bug in `rtiddsgen -convertToXml`
(symbolic references should be resolved to literals during conversion) or in the
C XCDR interpreter (should use the resolved DynamicType labels).
