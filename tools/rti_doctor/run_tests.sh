#!/bin/bash
# Run the rti_doctor test suites.
#
#   ./run_tests.sh            unit suite only (default)
#   ./run_tests.sh unit       same
#   ./run_tests.sh live       unit + live-domain integration
#   ./run_tests.sh vendor     cross-vendor e2e (needs Docker images)
#   ./run_tests.sh all        everything
#
# The three tiers differ in what they need, which is why they are separate:
#
#   unit    parses and imports rti.connextdds but creates no DDS entity, so it
#           needs neither NDDSHOME nor a license. This is the tier CI runs.
#   live    creates real participants on a local domain: needs a Connext
#           install and a license.
#   vendor  additionally needs Docker and the Cyclone/Fast DDS images.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TIER="${1:-unit}"

# Every suite that runs without a Connext license. Keep this list here rather
# than in CI config so the two cannot drift.
UNIT=(
    test_cli
    test_checks
    test_engine
    test_wire
    test_wire_discovery
    test_findings
    test_fixture_plan
    test_system_scan
    test_views
    test_topology
    test_domains
    test_doctor_e2e
)
LIVE=(test_live_integration test_scale test_data_representation_spike
    test_ownership_ignore_spike)
VENDOR=(
    test_fault_vendor_e2e
    test_fastdds_representation_spike
    test_rxo_vendor_e2e
    test_vendor_wire_e2e
    test_extensibility_vendor_e2e
    test_fastdds_extensibility_vendor_e2e
    test_fastdds_recording_service_e2e
    test_fastdds_type_object_e2e
)

case "$TIER" in
    unit)   MODULES=("${UNIT[@]}") ;;
    live)   MODULES=("${UNIT[@]}" "${LIVE[@]}") ;;
    vendor) MODULES=("${VENDOR[@]}") ;;
    all)    MODULES=("${UNIT[@]}" "${LIVE[@]}" "${VENDOR[@]}") ;;
    *)      echo "Unknown tier: $TIER (use unit | live | vendor | all)"; exit 2 ;;
esac

if [[ -n "${PYTHON:-}" ]]; then
    INTERPRETER="$PYTHON"
else
    source "$REPO_ROOT/scripts/python_env.sh"
    python_env_init "rti_doctor" "$REPO_ROOT"
    python_env_resolve_nddshome
    python_env_ensure_venv
    python_env_activate_venv
    INTERPRETER="$PYTHON_ENV_VENV_PYTHON"
    if [[ "$TIER" != "unit" ]]; then
        python_env_resolve_license_file
    fi
fi

QUALIFIED=()
for module in "${MODULES[@]}"; do
    QUALIFIED+=("tools.rti_doctor.test.$module")
done

echo "=== rti_doctor tests: $TIER (${#QUALIFIED[@]} module(s)) ==="
cd "$REPO_ROOT"

# Keep the whole run on disk. A 40-line tail is a fine terminal summary for a
# green run and useless for a red one: the failure names and tracebacks scroll
# past it, so a failing tier reports that it failed without saying what did.
# The tail stays; the log is the record the tail is a view of.
LOG_DIR="$SCRIPT_DIR/test_output"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run_tests_${TIER}.log"

set +e
PYTHONPATH="tools/rti_doctor${PYTHONPATH:+:$PYTHONPATH}" \
    "$INTERPRETER" -m unittest "${QUALIFIED[@]}" -v > "$LOG" 2>&1
STATUS=$?
set -e

tail -40 "$LOG"
if [[ $STATUS -ne 0 ]]; then
    echo
    echo "--- failing tests ---"
    grep -E "^(FAIL|ERROR): " "$LOG" || true
fi
echo
echo "Full output: $LOG"
exit $STATUS
