#!/bin/bash
# Start a DDS fixture for manual RTI Doctor inspection in another terminal.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TOOL_DIR/../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

usage() {
    cat <<'EOF'
Usage: run_manual_scenario.sh --scenario NAME [options]

Start a fixture in this terminal, then run the printed RTI Doctor command from
another terminal. Stop the fixture with Ctrl-C when finished.

Scenarios:
  healthy                     Connext writer; expect payload FULL.
  no-type-info                Writer without TypeObject propagation.
  large-data                  Fragmented Connext samples; expect INFO fragmentation.
  partition                   Writer in a named partition; Doctor mirrors it.
  bad-pair                    Writer plus incompatible Connext reader; expect RxO ERROR.
  rxo-compatible              Connext writer/reader with compatible RELIABILITY.
  rxo-reliability-mismatch    BEST_EFFORT writer and RELIABLE reader; expect RxO ERROR.
    connext-cyclone-compatible  Connext writer and Cyclone reader with compatible RELIABILITY.
    connext-cyclone-reliability-mismatch
                                                            Connext BEST_EFFORT writer and Cyclone RELIABLE reader.
    cyclone-connext-compatible  Cyclone writer and Connext reader with compatible RELIABILITY.
    cyclone-connext-reliability-mismatch
                                                            Cyclone BEST_EFFORT writer and Connext RELIABLE reader.
    connext-fastdds-compatible  Connext writer and Fast DDS reader with compatible RELIABILITY.
    connext-fastdds-reliability-mismatch
                                                            Connext BEST_EFFORT writer and Fast DDS RELIABLE reader.
    fastdds-connext-compatible  Fast DDS writer and Connext reader with compatible RELIABILITY.
    fastdds-connext-reliability-mismatch
                                                            Fast DDS BEST_EFFORT writer and Connext RELIABLE reader.
    fastdds-no-type-info         Fast DDS writer without TypeInformation metadata.

Options:
  -s, --scenario NAME         Required scenario name.
  -d, --domain ID             DDS domain (default: 42).
  -t, --topic NAME            Topic for single-fixture scenarios (default: DoctorManual).
  -p, --topic-prefix PREFIX   Topic prefix for RxO scenarios (default: ManualRxO).
      --duration SECONDS      Fixture lifetime (default: 300).
  -h, --help                  Show this help.
EOF
}

scenario=""
domain=42
topic="DoctorManual"
topic_prefix="ManualRxO"
duration=300
fastdds_image="${RTI_DOCTOR_FASTDDS_IMAGE:-rti-doctor-fastdds-e2e:3.6.2}"

while (($#)); do
    case "$1" in
        -s|--scenario)
            scenario="${2:?missing scenario name}"
            shift 2
            ;;
        -d|--domain)
            domain="${2:?missing domain ID}"
            shift 2
            ;;
        -t|--topic)
            topic="${2:?missing topic name}"
            shift 2
            ;;
        -p|--topic-prefix)
            topic_prefix="${2:?missing topic prefix}"
            shift 2
            ;;
        --duration)
            duration="${2:?missing duration}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$scenario" ]]; then
    echo "--scenario is required." >&2
    usage >&2
    exit 2
fi

if ! [[ "$domain" =~ ^[0-9]+$ ]]; then
    echo "--domain must be a non-negative integer." >&2
    exit 2
fi

case "$scenario" in
    healthy|no-type-info|large-data|partition|bad-pair|rxo-compatible|rxo-reliability-mismatch|\
    connext-cyclone-compatible|connext-cyclone-reliability-mismatch|\
    cyclone-connext-compatible|cyclone-connext-reliability-mismatch|\
    connext-fastdds-compatible|connext-fastdds-reliability-mismatch|\
    fastdds-connext-compatible|fastdds-connext-reliability-mismatch|fastdds-no-type-info)
        ;;
    *)
        echo "Unknown scenario: $scenario" >&2
        usage >&2
        exit 2
        ;;
esac

python_env_init "rti_doctor" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_rti_connext
python_env_sync_requirements "$TOOL_DIR/requirements.txt" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "textual:Textual"
python_env_resolve_license_file

run_fixture() {
    local mode="$1"
    local scenario_topic="$topic"
    if [[ "$topic" == "DoctorManual" ]]; then
        scenario_topic="DoctorManual_${mode}"
    fi
    cat <<EOF
Fixture started: mode=${mode}, domain=${domain}, topic=${scenario_topic}
In another terminal, run:
    ./tools/rti_doctor/run_rti_doctor.sh --domain ${domain}
In the GUI, select topic ${scenario_topic}.
Expected result: ${2}
EOF
    PYTHONPATH="$TOOL_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        python "$SCRIPT_DIR/fixture_publisher.py" --mode "$mode" \
        --domain "$domain" --topic "$scenario_topic" --duration "$duration"
}

start_rxo_endpoint() {
    local vendor="$1"
    local role="$2"
    local mode="$3"
    local endpoint

    if [[ "$vendor" == "connext" ]]; then
        endpoint="$SCRIPT_DIR/vendors/rxo_connext_matrix.py"
        PYTHONPATH="$TOOL_DIR${PYTHONPATH:+:$PYTHONPATH}" \
            python "$endpoint" --domain "$domain" --topic-prefix "$topic_prefix" \
            --role "$role" --mode "$mode" --scenarios reliability \
            --duration "$duration" --type-object-v1-only
    else
        endpoint="$SCRIPT_DIR/vendors/rxo_cyclone_matrix.py"
        PYTHONPATH="$TOOL_DIR${PYTHONPATH:+:$PYTHONPATH}" \
            python "$endpoint" --domain "$domain" --topic-prefix "$topic_prefix" \
            --role "$role" --mode "$mode" --scenarios reliability \
            --duration "$duration"
    fi
}

run_rxo_pair() {
    local writer_vendor="$1"
    local reader_vendor="$2"
    local mode="$3"
    local expected="$4"
    local title="$5"
    local reader_pid writer_pid

    cat <<EOF
${title} endpoints started: mode=${mode}, domain=${domain}, topic=${topic_prefix}_reliability
In another terminal, run:
    ./tools/rti_doctor/run_rti_doctor.sh --domain ${domain}
In the GUI, select topic ${topic_prefix}_reliability.
Expected result: ${expected}
EOF
    start_rxo_endpoint "$reader_vendor" reader "$mode" &
    reader_pid=$!
    sleep 1
    start_rxo_endpoint "$writer_vendor" writer "$mode" &
    writer_pid=$!

    cleanup() {
        kill "$reader_pid" "$writer_pid" 2>/dev/null || true
        wait "$reader_pid" "$writer_pid" 2>/dev/null || true
    }
    trap cleanup EXIT INT TERM
    wait "$reader_pid" "$writer_pid"
}

require_fastdds() {
    if ! command -v docker >/dev/null; then
        echo "Fast DDS scenarios require Docker." >&2
        exit 1
    fi
    if ! docker image inspect "$fastdds_image" >/dev/null 2>&1; then
        echo "Fast DDS image '$fastdds_image' is unavailable." >&2
        echo "Build it with: bash tools/rti_doctor/test/vendors/fastdds/build_image.sh" >&2
        exit 1
    fi
}

start_connext_fastdds_endpoint() {
    local role="$1"
    local reliability="$2"
    PYTHONPATH="$TOOL_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        python "$SCRIPT_DIR/vendors/extensibility_connext_endpoint.py" \
        --domain "$domain" --topic "$topic" --role "$role" \
        --extensibility final --schema fastdds --reliability "$reliability" \
        --durability volatile --deadline-seconds 1 --ownership shared \
        --representation xcdr1 --duration "$duration"
}

start_fastdds_endpoint() {
    local role="$1"
    local reliability="$2"
    docker run --rm --network host --entrypoint /doctor-extensibility-build/doctor_fastdds_final \
        -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 "$fastdds_image" \
        --domain "$domain" --topic "$topic" --role "$role" \
        --extensibility final --reliability "$reliability" --durability volatile \
        --deadline-seconds 1 --ownership shared --representation xcdr1 \
        --duration "$duration"
}

run_fastdds_pair() {
    local writer_vendor="$1"
    local mode="$2"
    local expected="$3"
    local reader_vendor="connext"
    local writer_reliability="reliable"
    local reader_reliability="reliable"
    local reader_pid writer_pid

    require_fastdds
    if [[ "$writer_vendor" == "connext" ]]; then
        reader_vendor="fastdds"
    fi
    if [[ "$mode" == "mismatch" ]]; then
        writer_reliability="best-effort"
    fi
    if [[ "$topic" == "DoctorManual" ]]; then
        topic="DoctorManual_${writer_vendor}_fastdds_${mode}"
    fi

    cat <<EOF
Connext/Fast DDS endpoints started: mode=${mode}, domain=${domain}, topic=${topic}
In another terminal, run:
    ./tools/rti_doctor/run_rti_doctor.sh --domain ${domain}
In the GUI, select topic ${topic}.
Expected result: ${expected}
EOF
    if [[ "$reader_vendor" == "connext" ]]; then
        start_connext_fastdds_endpoint reader "$reader_reliability" &
    else
        start_fastdds_endpoint reader "$reader_reliability" &
    fi
    reader_pid=$!
    sleep 1
    if [[ "$writer_vendor" == "connext" ]]; then
        start_connext_fastdds_endpoint writer "$writer_reliability" &
    else
        start_fastdds_endpoint writer "$writer_reliability" &
    fi
    writer_pid=$!

    cleanup() {
        kill "$reader_pid" "$writer_pid" 2>/dev/null || true
        wait "$reader_pid" "$writer_pid" 2>/dev/null || true
    }
    trap cleanup EXIT INT TERM
    wait "$reader_pid" "$writer_pid"
}

run_fastdds_no_type_info() {
    require_fastdds
    if [[ "$topic" == "DoctorManual" ]]; then
        topic="DoctorManual_fastdds_no_type_info"
    fi

    cat <<EOF
Fast DDS writer started without TypeInformation metadata: domain=${domain}, topic=${topic}
In another terminal, run:
    ./tools/rti_doctor/run_rti_doctor.sh --domain ${domain}
In the GUI, select topic ${topic}.
Expected result: type.no_type_info; verdict says not probed. The writer is
discoverable, but Doctor cannot resolve a DynamicType from suppressed metadata.
EOF
    docker run --rm --network host --entrypoint /doctor-extensibility-build/doctor_fastdds_final \
        -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 "$fastdds_image" \
        --domain "$domain" --topic "$topic" --role writer --extensibility final \
        --reliability reliable --durability volatile --deadline-seconds 1 \
        --ownership shared --representation xcdr1 --type-metadata none \
        --type-lookup disabled --duration "$duration"
}

case "$scenario" in
    healthy|no-type-info|large-data|partition|bad-pair)
        fixture_mode="${scenario//-/_}"
        case "$scenario" in
            healthy) expected="No active ERROR findings; payload FULL." ;;
            no-type-info) expected="type.no_type_info; verdict says not probed." ;;
            large-data) expected="data.fragmentation at INFO; payload FULL." ;;
            partition) expected="Reader matches after Doctor mirrors the partition." ;;
            bad-pair) expected="qos.rxo_mismatch naming RELIABILITY and OWNERSHIP." ;;
        esac
        run_fixture "$fixture_mode" "$expected"
        ;;
    rxo-compatible)
        run_rxo_pair connext connext compatible \
            "No active ERROR findings; endpoints match and exchange data." "Connext RxO"
        ;;
    rxo-reliability-mismatch)
        run_rxo_pair connext connext mismatch \
            "qos.rxo_mismatch naming RELIABILITY; endpoints remain unmatched." "Connext RxO"
        ;;
    connext-cyclone-compatible)
        run_rxo_pair connext cyclone compatible \
            "No active ERROR findings; endpoints match and exchange data." "Connext/Cyclone RxO"
        ;;
    connext-cyclone-reliability-mismatch)
        run_rxo_pair connext cyclone mismatch \
            "qos.rxo_mismatch naming RELIABILITY; endpoints remain unmatched." "Connext/Cyclone RxO"
        ;;
    cyclone-connext-compatible)
        run_rxo_pair cyclone connext compatible \
            "No active ERROR findings; endpoints match and exchange data." "Cyclone/Connext RxO"
        ;;
    cyclone-connext-reliability-mismatch)
        run_rxo_pair cyclone connext mismatch \
            "qos.rxo_mismatch naming RELIABILITY; endpoints remain unmatched." "Cyclone/Connext RxO"
        ;;
    connext-fastdds-compatible)
        run_fastdds_pair connext compatible \
            "No active ERROR findings; endpoints match and exchange data."
        ;;
    connext-fastdds-reliability-mismatch)
        run_fastdds_pair connext mismatch \
            "qos.rxo_mismatch naming RELIABILITY; endpoints remain unmatched."
        ;;
    fastdds-connext-compatible)
        run_fastdds_pair fastdds compatible \
            "Endpoints match and exchange data; the custom Fast DDS TypeObject may also report type.assignability."
        ;;
    fastdds-connext-reliability-mismatch)
        run_fastdds_pair fastdds mismatch \
            "qos.rxo_mismatch naming RELIABILITY; endpoints remain unmatched."
        ;;
    fastdds-no-type-info)
        run_fastdds_no_type_info
        ;;
esac