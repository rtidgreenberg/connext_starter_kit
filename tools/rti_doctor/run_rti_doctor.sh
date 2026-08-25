#!/bin/bash
# Run script for the RTI Doctor interop diagnostics tool.

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TOOLS_DIR/.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

echo "=== RTI Doctor ==="
echo
python_env_init "rti_doctor" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_rti_connext
# Every module the tool imports directly is verified here, not just the ones
# it declares. `rich` was imported by the TUI and declared nowhere, arriving
# only as a textual dependency - the kind of gap that holds until an upgrade
# and then fails at launch on someone else's machine.
python_env_sync_requirements "$SCRIPT_DIR/requirements.txt" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "textual:Textual" \
    "rich:Rich"
python_env_resolve_license_file

# --- Run Application ---
echo
cat <<'EOF'
⠀⠀⠀⠀⠀⠀⣀⠀⠀⠀⠀⠀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀    _______   _________  _____
⠀⠀⢀⣀⠐⠿⠿⠃⠀⠀⠀⠀⠻⠿⠆⢠⣀⠀⠀⠀⠀⠀   |_   __ \ |  _   _  ||_   _|
⠀⠀⣿⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢹⣷⠀⠀⠀⠀     | |__) ||_/ | | \_|  | |
⠀⠀⣿⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⡇⠀⠀⠀⠀     |  __ /     | |      | |
⠀⠀⠸⣇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣿⠁⠀⠀⠀⠀    _| |  \ \_  _| |_    _| |_
⠀⠀⠀⢻⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⠃⠀⠀⠀⠀⠀   |____| |___||_____|  |_____|
⠀⠀⠀⠈⢿⡄⠀⠀⠀⠀⠀⠀⠀⢀⣾⠃⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠈⢻⣦⠀⠀⠀⠀⠀⣠⡿⠁⠀⠀⠀⠀⠀⠀⠀    ______   _______
⠀⠀⠀⠀⠀⠀⠙⠻⣦⣤⣤⠾⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀   |_   _ `.|_   __ \
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀     | | `. \ | |__) |
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣇⠀⠀⠀⠀⠀⠀⠀⣠⣶⣦⡀     | |  | | |  __ /
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢿⡀⠀⠀⠀⠀⠀⢰⣿⠟⣿⡇    _| |_.' /_| |  \ \_  _
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢷⡄⠀⠀⠀⠀⠈⢿⣦⡿⠃   |______.'|____| |___|(_)
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⢶⣤⣄⣀⣀⣠⡿⠃
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠉⠉⠉⠀⠀⠀
EOF
echo "Starting RTI Doctor..."
echo "----------------------"
PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python -m rti_doctor "$@"
