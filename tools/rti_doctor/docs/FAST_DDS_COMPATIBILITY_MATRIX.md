# Fast DDS Compatibility Matrix

This is the living record of the Fast DDS configurations exercised by RTI
Doctor. A row is evidence for only the stated versions, direction, schema, and
settings. `Pass` in the data column means the receiving application obtained at
least one valid sample; it is stronger than endpoint discovery or a decoded
packet capture.

## Version Baseline

| Component | Version | Source |
|---|---|---|
| Connext | 7.7.0 | `NDDSHOME` used by the vendor tier |
| Fast DDS | 3.6.2 | `test/vendors/fastdds/Dockerfile` and `rti-doctor-fastdds-e2e:3.6.2` |
| Fast DDS-Gen | 4.3.0 | `test/vendors/fastdds/Dockerfile` |

All current Fast DDS fixture rows use a Docker container with host networking
and `FASTDDS_BUILTIN_TRANSPORTS=UDPv4`, unless the row explicitly says
otherwise. The Connext fixture applies the VENDOR XTypes compliance mask
(`0x000001A9`) before participant creation.

## Payload Deserialization

| Fast DDS role | Connext role | Type and endpoint configuration | Data received | Evidence |
|---|---|---|---|---|
| Writer | Reader | `FINAL` type; both endpoint QoS objects left at middleware defaults; Fast DDS writer leaves `DATA_REPRESENTATION` unset | Pass | `test_fastdds_extensibility_vendor_e2e.py::test_fastdds_and_connext_default_endpoint_qos_deserialize` |
| Writer | Recording Service -> Converter Service | Fast DDS writer endpoint QoS left at middleware defaults; Recording Service dynamically discovers the TypeObject without a registered local type and records XCDR; Converter Service exports CSV | Pass; verifies recorded `message == "DoctorExtensibility"` and `index > 0` | `test_fastdds_recording_service_e2e.py::test_records_fastdds_typeobject_payload_values` |
| Writer | DynamicData reader | `default-v2`: Fast DDS writer endpoint QoS left at middleware defaults; Connext resolves the full remote TypeObject and creates its default-QoS DynamicData reader from that `DynamicType` | Pass; verifies `message == "DoctorExtensibility"` and `index > 0` | `RTI_DOCTOR_TYPEOBJECT_PROFILE=default-v2 test_fastdds_type_object_e2e.py::test_fastdds_default_qos_type_object_dynamic_data_deserializes_samples` |
| Writer | DynamicData reader | `vendor-v2`: Fast DDS writer endpoint QoS left at middleware defaults; Connext VENDOR XTypes mask resolves the full remote TypeObject and creates its default-QoS DynamicData reader from that `DynamicType` | Pass; verifies `message == "DoctorExtensibility"` and `index > 0` | `RTI_DOCTOR_TYPEOBJECT_PROFILE=vendor-v2 test_fastdds_type_object_e2e.py::test_fastdds_default_qos_type_object_dynamic_data_deserializes_samples` |
| Writer | DynamicData reader | `default-v2`: default Connext XTypes mask and TypeObject v2/TypeLookup; `FINAL` type; reader created directly from the resolved remote `DynamicType`; Fast DDS uses explicit XCDR1, RELIABLE, VOLATILE, shared ownership, and a 1-second deadline | Pass; verifies `message == "DoctorExtensibility"` and `index > 0` | `RTI_DOCTOR_TYPEOBJECT_PROFILE=default-v2 test_fastdds_type_object_e2e.py::test_fastdds_type_object_dynamic_data_reader_deserializes_samples` |
| Writer | DynamicData reader | `vendor-v2`: Connext VENDOR XTypes mask and TypeObject v2/TypeLookup; otherwise the same as `default-v2` | Pass; verifies `message == "DoctorExtensibility"` and `index > 0` | `RTI_DOCTOR_TYPEOBJECT_PROFILE=vendor-v2 test_fastdds_type_object_e2e.py::test_fastdds_type_object_dynamic_data_reader_deserializes_samples` |
| Writer and reader | Reader and writer | Matching `FINAL` to `FINAL`; explicit XCDR1; RELIABLE, VOLATILE, shared ownership, 1-second deadline | Pass both directions | `test_fastdds_extensibility_vendor_e2e.py::test_*_matrix` |
| Writer and reader | Reader and writer | Matching `APPENDABLE` to `APPENDABLE`; explicit XCDR1; RELIABLE, VOLATILE, shared ownership, 1-second deadline | Pass both directions | `test_fastdds_extensibility_vendor_e2e.py::test_*_matrix` |
| Writer and reader | Reader and writer | Matching `FINAL` to `FINAL`; explicit XCDR2 | Pass both directions | `test_fastdds_extensibility_vendor_e2e.py::test_data_representation_compatibility_matrix` |
| Writer | Reader | `FINAL`; explicit XCDR1; RELIABLE, VOLATILE, shared ownership; Doctor observes the pair | Pass | `test_fault_vendor_e2e.py::test_fastdds_writer_to_connext_reader_healthy` |
| Reader | Writer | `FINAL`; explicit XCDR1; RELIABLE, VOLATILE, shared ownership; Doctor observes the pair | Pass | `test_fault_vendor_e2e.py::test_connext_writer_to_fastdds_reader_healthy` |

The first row is the strongest default-QoS result: neither endpoint QoS object
is modified. It does not establish shared-memory delivery because the fixture
intentionally limits Fast DDS to UDPv4.

## Expected Non-Delivery

These cases are compatibility controls, not successful deserialization claims.

| Configuration | Expected result | Evidence |
|---|---|---|
| `FINAL` writer with `APPENDABLE` reader, or the reverse | Endpoints may match but no sample crosses | `test_fastdds_extensibility_vendor_e2e.py::test_*_matrix` |
| XCDR1 endpoint paired with XCDR2-only endpoint, either direction | No match and no samples; middleware reports `DataRepresentation` | `test_fastdds_extensibility_vendor_e2e.py::test_data_representation_compatibility_matrix` |
| Incompatible reliability, durability, deadline, ownership, or data representation, either direction | No match and no samples; Doctor reports the specific RxO policy | `test_fault_vendor_e2e.py::TestConnextFastDdsFaultControls` |
| `vendor-v1`: Connext VENDOR XTypes mask with inline TypeObject v1 and TypeLookup disabled | Connext discovers the Fast DDS writer but cannot resolve a usable `DynamicType`; no DynamicData reader is created | `RTI_DOCTOR_TYPEOBJECT_PROFILE=vendor-v1 test_fastdds_type_object_e2e.py::test_fastdds_type_object_dynamic_data_reader_deserializes_samples` |

## Discovery And Wire Evidence Only

These results do not prove that a Connext application deserialized a Fast DDS
sample, so they are tracked separately.

| Fast DDS version | Configuration | Result | Evidence |
|---|---|---|---|
| 3.6.2 | Full generated TypeInformation/TypeObject, `FINAL` type | Connext resolves a usable `DynamicType` | `test_fastdds_type_object_e2e.py::test_fastdds_writer_type_object_deserializes_in_connext` |
| 3.6.2 | Full metadata with TypeLookup enabled | Connext resolves a usable `DynamicType` | `test_fastdds_type_metadata_spike.py::test_fastdds_typelookup_resolves_dynamic_type_in_connext` |
| 3.6.2 | Fast DDS writer leaves `DATA_REPRESENTATION` unset | Empty advertisement behaves as XCDR1: matches XCDR1 and is rejected by XCDR2-only reader | `test_fastdds_representation_spike.py` |
| 3.6.2 | Upstream HelloWorld publisher/subscriber | RTI Doctor captures real RTPS user data and reports the Fast DDS product version | `test_vendor_wire_e2e.py::TestFastDDSWireE2E` |
| 2.14.6 | Historical vendor-generated payload capture | PCAPNG contains XCDR1 encapsulation (`0x0001`); no current application-level deserialization assertion | `docs/BUILD_SUMMARY.md` |

## Maintenance Rule

When changing the Fast DDS image version, Connext version, generated fixture
schema, transport setting, compliance mask, or test outcome:

1. Update the version baseline and every affected row in this file.
2. Run `./tools/rti_doctor/run_tests.sh vendor` with the intended image.
3. Retain any generated failure evidence under `tools/rti_doctor/test_output/`
   and record a link or concise result in the affected row.
4. Keep historical rows, marking them historical instead of treating them as
   coverage for the current fixture.