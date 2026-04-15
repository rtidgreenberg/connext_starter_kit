#!/usr/bin/env bash
# run_order_tests.sh — Run Distributed Logger ordering tests with both the
# Python subscriber (bulk/sorted modes) and rtiddsspy, then compare results.
#
# Usage:  ./run_order_tests.sh [DOMAIN_ID] [COUNT]
#   DOMAIN_ID  DDS domain (default: 0)
#   COUNT      Messages per level per pattern (default: 10)

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/../../connext_dds_env/bin/python"
PUB="$SCRIPT_DIR/publisher.py"
SUB="$SCRIPT_DIR/subscriber.py"
OUT_DIR="$SCRIPT_DIR/test_output"

DOMAIN=${1:-0}
COUNT=${2:-10}
SUB_PID=""
SPY_PID=""

# Ensure output directory exists, clean previous results
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

cleanup() {
    echo "Cleaning up background processes..."
    [[ -n "$SUB_PID" ]] && kill -INT "$SUB_PID" 2>/dev/null || true
    [[ -n "$SPY_PID" ]] && kill -INT "$SPY_PID" 2>/dev/null || true
    wait "$SUB_PID" 2>/dev/null || true
    wait "$SPY_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ============================================================
# TEST 1: Python subscriber — bulk mode (take_async, instance-grouped)
# ============================================================
echo "============================================================"
echo "TEST 1: Python subscriber — bulk mode (take_async)"
echo "============================================================"

"$PYTHON" -u "$SUB" -d "$DOMAIN" -m bulk > "$OUT_DIR/sub_bulk.txt" 2>&1 &
SUB_PID=$!
sleep 3

"$PYTHON" -u "$PUB" -d "$DOMAIN" -p round-robin -n "$COUNT" > "$OUT_DIR/pub_bulk.txt" 2>&1
sleep 2
kill -INT "$SUB_PID" 2>/dev/null || true
wait "$SUB_PID" 2>/dev/null || true
SUB_PID=""

echo "  Publisher output -> test_output/pub_bulk.txt"
echo "  Subscriber output -> test_output/sub_bulk.txt"

# ============================================================
# TEST 2: Python subscriber — sorted mode (take + sort by source_timestamp)
# ============================================================
echo ""
echo "============================================================"
echo "TEST 2: Python subscriber — sorted mode (source_timestamp)"
echo "============================================================"

"$PYTHON" -u "$SUB" -d "$DOMAIN" -m sorted > "$OUT_DIR/sub_sorted.txt" 2>&1 &
SUB_PID=$!
sleep 3

"$PYTHON" -u "$PUB" -d "$DOMAIN" -p round-robin -n "$COUNT" > "$OUT_DIR/pub_sorted.txt" 2>&1
sleep 2
kill -INT "$SUB_PID" 2>/dev/null || true
wait "$SUB_PID" 2>/dev/null || true
SUB_PID=""

echo "  Publisher output -> test_output/pub_sorted.txt"
echo "  Subscriber output -> test_output/sub_sorted.txt"

# ============================================================
# TEST 3: rtiddsspy
# ============================================================
echo ""
echo "============================================================"
echo "TEST 3: rtiddsspy -printSample"
echo "============================================================"

rtiddsspy -domainId "$DOMAIN" -printSample > "$OUT_DIR/rtiddsspy_raw.txt" 2>&1 &
SPY_PID=$!
sleep 3

"$PYTHON" -u "$PUB" -d "$DOMAIN" -p round-robin -n "$COUNT" > "$OUT_DIR/pub_spy.txt" 2>&1
sleep 2
kill -INT "$SPY_PID" 2>/dev/null || true
wait "$SPY_PID" 2>/dev/null || true
SPY_PID=""

# Extract level + message pairs from rtiddsspy output
grep -E '^level:|^message:' "$OUT_DIR/rtiddsspy_raw.txt" \
    | paste - - > "$OUT_DIR/rtiddsspy_parsed.txt" 2>/dev/null || true

echo "  Publisher output  -> test_output/pub_spy.txt"
echo "  rtiddsspy raw     -> test_output/rtiddsspy_raw.txt"
echo "  rtiddsspy parsed  -> test_output/rtiddsspy_parsed.txt"

# ============================================================
# COMPARISON SUMMARY
# ============================================================
echo ""
echo "============================================================"
echo "COMPARISON SUMMARY"
echo "============================================================"

analyze() {
    local label=$1
    local file=$2

    if [ ! -f "$file" ]; then
        echo "  $label: FILE NOT FOUND"
        return
    fi

    local total
    total=$(grep -c '\[seq=' "$file" 2>/dev/null || echo 0)
    local ooo
    ooo=$(grep -c 'OOO' "$file" 2>/dev/null || echo 0)

    echo "  $label: $total msgs received, $ooo out-of-order"
}

analyze_spy() {
    local file=$1
    if [ ! -f "$file" ]; then
        echo "  rtiddsspy:         FILE NOT FOUND"
        return
    fi

    # Count messages by looking for [seq=N] in the raw output
    local total
    total=$(grep -coP '\[seq=\d+\]' "$file" 2>/dev/null || echo 0)

    # Check if seq numbers are monotonically increasing
    local ooo
    ooo=$(grep -oP '\[seq=\K\d+' "$file" \
        | awk 'NR>1 && $1 < prev {count++} {prev=$1} END {print count+0}' 2>/dev/null || echo 0)

    echo "  rtiddsspy:         $total msgs received, $ooo out-of-order"
}

analyze "Python bulk:   " "$OUT_DIR/sub_bulk.txt"
analyze "Python sorted: " "$OUT_DIR/sub_sorted.txt"
analyze_spy "$OUT_DIR/rtiddsspy_raw.txt"

echo ""
echo "Detailed outputs in: $OUT_DIR/"
echo "Done."
