# DDS Debug Game

A scenario-driven DDS troubleshooting tool. It generates editable participant
scripts while the package-owned runtime creates and observes DDS entities.

```bash
./tools/rti_debug_game/run_rti_debug_game.sh
./tools/rti_debug_game/run_rti_debug_game.sh --generate --level L01
./tools/rti_debug_game/run_rti_debug_game.sh --run --level L01
./tools/rti_debug_game/run_rti_debug_game.sh --reset --level L01
./tools/rti_debug_game/run_tests.sh
```

L01 deliberately starts broken: its writer is `BEST_EFFORT` while its reader
requires `RELIABLE`. Generate the workspace, diagnose domain `42` using RTI
Admin Console, then edit
`tools/rti_debug_game/run/participant_aster_vehicle_supervisor.py` to repair
the writer QoS. The private control domain planned for future multi-process
rounds is `100`; the first slice reports directly from its finite runner.

Only `run/participant_*.py` files are intended for player edits. `run/` is
ignored by Git; `--reset` restores the original fault.
