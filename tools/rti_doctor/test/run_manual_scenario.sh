#!/bin/bash
# Start a DDS fixture for manual RTI Doctor inspection in another terminal.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TOOL_DIR/../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

usage() {
    cat <<'EOF'
Usage: run_manual_scenario.sh [--scenario NAME] [options]

Start a fixture in this terminal, then run the printed RTI Doctor command from
another terminal. Stop the fixture with Ctrl-C when finished.
Omit --scenario in a terminal to select one with the keyboard.

Scenarios:
  healthy                     Connext writer; expect payload FULL.
  no-type-info                Writer without TypeObject propagation.
  large-data                  Fragmented Connext samples; expect INFO fragmentation.
  partition                   Writer in a named partition; Doctor mirrors it.
  bad-pair                    Writer plus incompatible Connext reader; expect RxO ERROR.
    mixed-qos-topology          Random mixed topology: green, yellow, and red topics.
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
    -s, --scenario NAME         Scenario name (interactive selector when omitted).
  -d, --domain ID             DDS domain (default: 42).
  -t, --topic NAME            Topic for single-fixture scenarios (default: DoctorManual).
  -p, --topic-prefix PREFIX   Topic prefix for RxO scenarios (default: ManualRxO).
      --duration SECONDS      Fixture lifetime (default: 300).
      --mixed-seed N          mixed-qos-topology: replay a previous run's
                              scenario. Omitted, the fixture draws a fresh seed
                              and prints it.
  -h, --help                  Show this help.
EOF
}

scenario=""
domain=42
topic="DoctorManual"
topic_prefix="ManualRxO"
duration=300
# Empty means "let the fixture draw one and print it". A randomized scenario is
# only usable if a run that found something can be replayed, and this scenario
# is the main way anyone runs the mixed_qos fixture by hand - so the passthrough
# has to exist here or the printed seed is unusable.
mixed_seed=""
fastdds_image="${RTI_DOCTOR_FASTDDS_IMAGE:-rti-doctor-fastdds-e2e:3.6.2}"
# Every Connext participant these scenarios start is named from this prefix, so
# the Doctor report and the topology table say which endpoint is which instead
# of showing "(unnamed)" beside a peer that named itself. The vendor and role are
# appended per endpoint. Fast DDS and Cyclone participants keep whatever name
# their own vendor assigns - the fixtures do not set it.
MANUAL_PARTICIPANT_PREFIX="doctor_manual"
scenarios=(
    healthy
    no-type-info
    large-data
    partition
    bad-pair
    mixed-qos-topology
    rxo-compatible
    rxo-reliability-mismatch
    connext-cyclone-compatible
    connext-cyclone-reliability-mismatch
    cyclone-connext-compatible
    cyclone-connext-reliability-mismatch
    connext-fastdds-compatible
    connext-fastdds-reliability-mismatch
    fastdds-connext-compatible
    fastdds-connext-reliability-mismatch
    fastdds-no-type-info
)

select_scenario() {
    local selected=0 key sequence index

    while true; do
        printf '\033[H\033[J'
        echo "RTI Doctor manual scenarios"
        echo
        for index in "${!scenarios[@]}"; do
            if ((index == selected)); then
                printf '  > %s\n' "${scenarios[index]}"
            else
                printf '    %s\n' "${scenarios[index]}"
            fi
        done
        echo
        echo "Up/Down: select  Enter: start  q: quit"

        IFS= read -rsn1 key
        if [[ "$key" == $'\e' ]]; then
            sequence=""
            IFS= read -rsn2 -t 0.1 sequence || true
            key+="$sequence"
        fi

        case "$key" in
            $'\e[A'|k)
                selected=$(( (selected - 1 + ${#scenarios[@]}) % ${#scenarios[@]} ))
                ;;
            $'\e[B'|j)
                selected=$(( (selected + 1) % ${#scenarios[@]} ))
                ;;
            "")
                scenario="${scenarios[selected]}"
                return 0
                ;;
            q|Q)
                return 1
                ;;
        esac
    done
}

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
        --mixed-seed)
            mixed_seed="$2"
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
    if [[ -t 0 && -t 1 ]]; then
        select_scenario || exit 0
    else
        echo "--scenario is required when stdin or stdout is not a terminal." >&2
        usage >&2
        exit 2
    fi
fi

if ! [[ "$domain" =~ ^[0-9]+$ ]]; then
    echo "--domain must be a non-negative integer." >&2
    exit 2
fi

valid_scenario=false
for known_scenario in "${scenarios[@]}"; do
    if [[ "$scenario" == "$known_scenario" ]]; then
        valid_scenario=true
        break
    fi
done
if [[ "$valid_scenario" != true ]]; then
    echo "Unknown scenario: $scenario" >&2
    usage >&2
    exit 2
fi

python_env_init "rti_doctor" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_rti_connext
python_env_sync_requirements "$TOOL_DIR/requirements.txt" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "textual:Textual"
python_env_resolve_license_file

# Cleanup takes its process ids and container names as arguments, because an
# EXIT trap runs AFTER the enclosing function has returned. The previous
# cleanups closed over the scenario functions' `local` variables, which no
# longer exist by then: under `set -u` the very first line -
# kill "$reader_pid" - was fatal, so a scenario that ran to completion printed
# "unbound variable" and exited 1, and the abort happened before `docker rm`,
# leaving rti-doctor-manual-* containers running. Only the normal-completion
# path was affected, because on Ctrl-C the trap fires while the locals are
# still in scope - so this bit exactly the case nobody watches.
#
# Arguments are `PID... -- CONTAINER...`, and callers register the trap with
# the values already substituted (quoted with %q) rather than by name.
cleanup_scenario() {
    local pids=() containers=() after_separator=0 item
    for item in "$@"; do
        if [[ "$item" == "--" ]]; then
            after_separator=1
        elif (( after_separator )); then
            containers+=("$item")
        else
            pids+=("$item")
        fi
    done
    if (( ${#pids[@]} )); then
        kill "${pids[@]}" 2>/dev/null || true
        wait "${pids[@]}" 2>/dev/null || true
    fi
    if (( ${#containers[@]} )); then
        docker rm --force "${containers[@]}" >/dev/null 2>&1 || true
    fi
}

# Register the EXIT cleanup for a scenario, capturing its arguments now.
# INT and TERM exit rather than cleaning up themselves, so every route out of a
# scenario - normal completion, Ctrl-C, SIGTERM - runs cleanup exactly once,
# through EXIT.
trap_scenario_cleanup() {
    local quoted
    quoted="$(printf '%q ' "$@")"
    trap "cleanup_scenario ${quoted}" EXIT
    trap 'exit 130' INT TERM
}

# What the participant of VENDOR in ROLE will be called in discovery, for the
# banner. Only the Connext fixtures accept a name; the others announce whatever
# their vendor picked, so say so rather than printing a name that will not appear.
participant_label() {
    local vendor="$1" role="$2"
    if [[ "$vendor" == "connext" ]]; then
        printf '%s_connext_%s' "$MANUAL_PARTICIPANT_PREFIX" "$role"
    else
        printf '%s default name' "$vendor"
    fi
}

run_fixture() {
    local mode="$1"
    local scenario_topic="$topic"
    if [[ "$topic" == "DoctorManual" ]]; then
        scenario_topic="DoctorManual_${mode}"
    fi
    cat <<EOF
Fixture started: mode=${mode}, domain=${domain}, topic=${scenario_topic}
Participant: ${MANUAL_PARTICIPANT_PREFIX}
In another terminal, run:
    ./tools/rti_doctor/run_rti_doctor.sh --domain ${domain}
In the GUI, select topic ${scenario_topic}.
Expected result: ${2}
EOF
    PYTHONPATH="$TOOL_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        python "$SCRIPT_DIR/fixture_publisher.py" --mode "$mode" \
        --domain "$domain" --topic "$scenario_topic" --duration "$duration" \
        --participant-name "$MANUAL_PARTICIPANT_PREFIX"
}

run_mixed_qos_topology() {
    local topic_prefix="$topic"
    if [[ "$topic_prefix" == "DoctorManual" ]]; then
        topic_prefix="DoctorManualMixed"
    fi
    cat <<EOF
Random mixed topology started: domain=${domain}, topics=${topic_prefix}_01 through ${topic_prefix}_06
Participants: ${MANUAL_PARTICIPANT_PREFIX}_app_1 through ${MANUAL_PARTICIPANT_PREFIX}_app_5
The scenario is drawn fresh per run. It contains compatible green topics,
yellow topics with disabled type propagation and a different type name, and
red topics with weakened writer QoS. Endpoint counts and hosting applications
vary per run. At least one topic leaves OWNERSHIP EXCLUSIVE on two or more writers.
The fixture prints each topic's shape below, and its seed last: pass that back
as --mixed-seed to replay this exact scenario.
In another terminal, run:
    ./tools/rti_doctor/run_rti_doctor.sh --domain ${domain}
Inspect any ${topic_prefix}_NN topic. Expected result: matching writer-reader
pairs alongside qos.rxo_mismatch findings naming the policies printed for that
topic.
EOF
    PYTHONPATH="$TOOL_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        python "$SCRIPT_DIR/fixture_publisher.py" --mode mixed_qos \
        --domain "$domain" --topic "$topic_prefix" --duration "$duration" \
        ${mixed_seed:+--mixed-seed "$mixed_seed"} \
        --participant-name "$MANUAL_PARTICIPANT_PREFIX"
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
            --duration "$duration" --type-object-v1-only \
            --participant-name "${MANUAL_PARTICIPANT_PREFIX}_connext_${role}"
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
Participants: writer=$(participant_label "$writer_vendor" writer), reader=$(participant_label "$reader_vendor" reader)
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

    trap_scenario_cleanup "$reader_pid" "$writer_pid"
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
        --representation xcdr1 --duration "$duration" \
        --participant-name "${MANUAL_PARTICIPANT_PREFIX}_connext_${role}"
}

start_fastdds_endpoint() {
    local container_name="$1"
    local role="$2"
    local reliability="$3"
    docker run --rm --name "$container_name" --network host \
        --entrypoint /doctor-extensibility-build/doctor_fastdds_final \
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
    local reader_container="rti-doctor-manual-$$_$RANDOM-reader"
    local writer_container="rti-doctor-manual-$$_$RANDOM-writer"

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
Participants: writer=$(participant_label "$writer_vendor" writer), reader=$(participant_label "$reader_vendor" reader)
In another terminal, run:
    ./tools/rti_doctor/run_rti_doctor.sh --domain ${domain}
In the GUI, select topic ${topic}.
Expected result: ${expected}
EOF
    if [[ "$reader_vendor" == "connext" ]]; then
        start_connext_fastdds_endpoint reader "$reader_reliability" &
    else
        start_fastdds_endpoint "$reader_container" reader "$reader_reliability" &
    fi
    reader_pid=$!
    sleep 1
    if [[ "$writer_vendor" == "connext" ]]; then
        start_connext_fastdds_endpoint writer "$writer_reliability" &
    else
        start_fastdds_endpoint "$writer_container" writer "$writer_reliability" &
    fi
    writer_pid=$!

    trap_scenario_cleanup "$reader_pid" "$writer_pid" \
        -- "$reader_container" "$writer_container"
    wait "$reader_pid" "$writer_pid"
}

run_fastdds_no_type_info() {
    local container="rti-doctor-manual-$$_$RANDOM-no-type-info"
    local docker_pid

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
    docker run --rm --name "$container" --network host \
        --entrypoint /doctor-extensibility-build/doctor_fastdds_final \
        -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 "$fastdds_image" \
        --domain "$domain" --topic "$topic" --role writer --extensibility final \
        --reliability reliable --durability volatile --deadline-seconds 1 \
        --ownership shared --representation xcdr1 --type-metadata none \
        --type-lookup disabled --duration "$duration" &
    docker_pid=$!

    trap_scenario_cleanup "$docker_pid" -- "$container"
    wait "$docker_pid"
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
    mixed-qos-topology)
        run_mixed_qos_topology
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