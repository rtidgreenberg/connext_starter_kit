#!/bin/bash
# Launch rti_view from the workspace root.
# Usage: ./run_rti_view.sh -d 0 -t Square -f x -m plot --history 30

exec "$(dirname "$0")/tools/rti_view/run_rti_view.sh" "$@"
