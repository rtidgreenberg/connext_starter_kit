#!/bin/bash
# Static checks for rti_doctor: undefined names and unused imports.
#
# Deliberately pyflakes and not a style linter. This codebase uses 2-space
# indents that pycodestyle rejects on every line, and the noise would bury the
# two classes of finding that have actually shipped bugs here:
#
#   * undefined name  - `topology` was used in two headless entry points and
#                       imported in neither, so `--all` crashed after doing the
#                       whole sweep (CODE_REVIEW_2026-08-06 H1).
#   * unused import   - deleting SweepScreen took `import asyncio` with it while
#                       ReportScreen still used it, and the full suite stayed
#                       green (CODE_REVIEW_2026-08-06 I6 follow-on).
#
# Needs no Connext install and no license: pyflakes parses, it does not import.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import pyflakes" 2>/dev/null; then
    echo "pyflakes is not installed. Install it with:"
    echo "    $PYTHON -m pip install pyflakes"
    exit 2
fi

# Generated IDL support is excluded: it is machine-written, regenerated from
# .idl, and its unused imports are not ours to fix.
EXCLUDE='test/vendors/shared_idl/generated/'

REPORT="$(mktemp)"
trap 'rm -f "$REPORT"' EXIT
"$PYTHON" -m pyflakes rti_doctor test > "$REPORT" 2>&1 || true

# The heredoc is python's stdin, so the report is passed by path, not piped.
"$PYTHON" - "$EXCLUDE" "$REPORT" <<'PY'
import sys

exclude, report = sys.argv[1], sys.argv[2]
findings = []
for line in open(report, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line or exclude in line:
        continue
    # "path:line:col: message" - re-read the cited line so `# noqa` is honored,
    # which pyflakes itself does not do.
    parts = line.split(":", 3)
    if len(parts) == 4 and parts[1].isdigit():
        path, number = parts[0], int(parts[1])
        try:
            with open(path, encoding="utf-8") as handle:
                source = handle.readlines()
            if number <= len(source) and "# noqa" in source[number - 1]:
                continue
        except OSError:
            pass
    findings.append(line)

for finding in findings:
    print(finding)
print()
if findings:
    print(f"FAIL: {len(findings)} finding(s).")
    sys.exit(1)
print("OK: no undefined names or unused imports.")
PY
