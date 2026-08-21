#!/bin/bash
# Try Connext 7.7 TypeObject profiles against one Fast DDS topic.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR=""
DOMAIN=""
TOPIC=""
SETTLE=20
TYPE_WAIT=10
PROBE_TIMEOUT=10
NDDSHOME_77="${RTI_DOCTOR_NDDSHOME_77:-$HOME/rti_connext_dds-7.7.0}"

usage() {
    cat <<'EOF'
Usage: run_version_matrix.sh --domain ID --topic TOPIC [options]

Run fresh Connext 7.7 rti_doctor processes against one topic. The report UI
offers this runner only for a selected Fast DDS writer. It first confirms that
the requested topic is visible, then tries:

    default-v2  Connext default XTypes mask and TypeObject V2/TypeLookup
    vendor-v2   VENDOR XTypes mask and TypeObject V2/TypeLookup
    vendor-v1   VENDOR XTypes mask and inline TypeObject V1

The matrix stops at the first profile whose targeted diagnostic exits without
ERROR findings. A successful profile is evidence about this observer only; it
does not prove the same profile fixes another application or RTI service.

Options:
  -d, --domain ID              DDS domain to observe (required).
  -t, --topic TOPIC            Topic whose writer must be Fast DDS (required).
      --nddshome-7.7 PATH      Native Connext 7.7 installation.
      --settle SECONDS         Discovery settle time per run (default: 20).
      --type-wait SECONDS      Type-resolution wait per run (default: 10).
      --probe-timeout SECONDS  Endpoint probe time per run (default: 10).
  -o, --output-dir PATH        Evidence output directory.
  -h, --help                   Show this help.

Choose a topic with one Fast DDS writer. Current `--topic` selection prefers
the first discovered writer and cannot yet choose an endpoint by GUID.
EOF
}

while (($#)); do
    case "$1" in
        -d|--domain) DOMAIN="${2:?missing domain ID}"; shift 2 ;;
        -t|--topic) TOPIC="${2:?missing topic name}"; shift 2 ;;
        --nddshome-7.7) NDDSHOME_77="${2:?missing 7.7 NDDSHOME}"; shift 2 ;;
        --settle) SETTLE="${2:?missing settle seconds}"; shift 2 ;;
        --type-wait) TYPE_WAIT="${2:?missing type wait seconds}"; shift 2 ;;
        --probe-timeout) PROBE_TIMEOUT="${2:?missing probe seconds}"; shift 2 ;;
        -o|--output-dir) OUTPUT_DIR="${2:?missing output directory}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if ! [[ "$DOMAIN" =~ ^[0-9]+$ ]]; then
    echo "--domain must be a non-negative integer." >&2
    exit 2
fi
if [[ -z "$TOPIC" ]]; then
    echo "--topic is required so the probe has an explicit target." >&2
    exit 2
fi
for value in "$SETTLE" "$TYPE_WAIT" "$PROBE_TIMEOUT"; do
    if ! [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        echo "--settle, --type-wait, and --probe-timeout must be non-negative numbers." >&2
        exit 2
    fi
done
if [[ ! -d "$NDDSHOME_77" ]]; then
    echo "Required Connext 7.7 runtime is missing: $NDDSHOME_77" >&2
    exit 3
fi

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$SCRIPT_DIR/test_output/fastdds_typeobject_matrix_$(date +%Y%m%d_%H%M%S)"
fi
mkdir -p "$OUTPUT_DIR"
MANIFEST="$OUTPUT_DIR/manifest.txt"
SUMMARY="$OUTPUT_DIR/summary.txt"

run_doctor() {
    local output="$1"
    shift
    env -u NDDS_XTYPES_COMPLIANCE_MASK NDDSHOME="$NDDSHOME_77" \
        "$SCRIPT_DIR/run_rti_doctor.sh" "$@" -o "$output"
}

{
    echo "RTI Doctor Fast DDS TypeObject probe matrix"
    echo "Started: $(date -Is)"
    echo "Domain: $DOMAIN"
    echo "Topic: $TOPIC"
    echo "NDDSHOME: $NDDSHOME_77"
    echo "Settle seconds: $SETTLE"
    echo "Type wait seconds: $TYPE_WAIT"
    echo "Probe timeout seconds: $PROBE_TIMEOUT"
    echo "Profiles: default/V2, vendor/V2, vendor/V1"
} >"$MANIFEST"

PREFLIGHT="$OUTPUT_DIR/preflight_system_report.txt"
echo "MATRIX_PROGRESS preflight running"
set +e
run_doctor "$PREFLIGHT" --system --domain "$DOMAIN" --settle "$SETTLE" \
    --type-wait "$TYPE_WAIT" >"$OUTPUT_DIR/preflight.stdout.txt" \
    2>"$OUTPUT_DIR/preflight.stderr.txt"
set -e

if ! grep -Fq "$TOPIC" "$PREFLIGHT"; then
    echo "MATRIX_PROGRESS preflight failed"
    echo "Topic '$TOPIC' was not observed in the passive preflight; not starting a probe." >&2
    exit 4
fi
echo "MATRIX_PROGRESS preflight complete"

printf '%-10s %-10s %-32s %s\n' "PROFILE" "EXIT" "RESULT" "REPORT" >"$SUMMARY"
for profile in default-v2 vendor-v2 vendor-v1; do
    run_dir="$OUTPUT_DIR/$profile"
    mkdir -p "$run_dir"
    report_path="$run_dir/topic_report.txt"
    args=(--topic "$TOPIC" --domain "$DOMAIN" --settle "$SETTLE"
          --type-wait "$TYPE_WAIT" --probe-timeout "$PROBE_TIMEOUT")
    if [[ "$profile" == vendor-* ]]; then
        args+=(--xtypes-compliance vendor)
    else
        args+=(--xtypes-compliance default)
    fi
    if [[ "$profile" == *-v1 ]]; then
        args+=(--type-object-v1-only)
    fi
    echo "MATRIX_PROGRESS $profile running"
    set +e
    run_doctor "$report_path" "${args[@]}" >"$run_dir/launcher.stdout.txt" \
        2>"$run_dir/launcher.stderr.txt"
    status=$?
    set -e
    result="ERROR findings or startup failure"
    if [[ $status -eq 0 ]]; then
        result="no ERROR findings"
    fi
    printf '%-10s %-10s %-32s %s\n' "$profile" "$status" "$result" \
        "$profile/topic_report.txt" >>"$SUMMARY"
    echo "MATRIX_PROGRESS $profile $result"
    if [[ $status -eq 0 ]]; then
        echo "Profile '$profile' completed without ERROR findings; stopping matrix."
        break
    fi
done

echo "Evidence written to: $OUTPUT_DIR"
cat "$SUMMARY"