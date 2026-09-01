"""Package-owned scenario definitions for the first Debug Game slice."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Participant:
    process_id: str
    name: str
    writes: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    level_id: str
    title: str
    difficulty: int
    issue_categories: tuple[str, ...]
    participants: tuple[Participant, ...]
    topic: str
    type_name: str
    expected_writer: str
    expected_reader: str
    samples_per_round: int = 10


L01 = Scenario(
    level_id="L01",
    title="Motion command is not armed",
    difficulty=1,
    issue_categories=("Reliability",),
    topic="VehicleCommand",
    type_name="autonomy::VehicleCommand",
    expected_writer="aster_vehicle_supervisor",
    expected_reader="helios_motion_controller",
    participants=(
        Participant("aster_vehicle_supervisor", "AsterVehicleSupervisor", writes=("VehicleCommand",)),
        Participant("helios_motion_controller", "HeliosMotionController", reads=("VehicleCommand",)),
    ),
)


CATALOG = {L01.level_id: L01}
