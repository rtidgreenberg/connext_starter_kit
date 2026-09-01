"""Package-owned scenario definitions for the first Debug Game slice."""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Participant:
    process_id: str
    name: str
    writes: Tuple[str, ...] = ()
    reads: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    level_id: str
    title: str
    difficulty: int
    issue_categories: Tuple[str, ...]
    participants: Tuple[Participant, ...]
    topic: str
    type_name: str
    expected_writer: str
    expected_reader: str
    fault: str
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
    fault="reliability",
    participants=(
        Participant("aster_vehicle_supervisor", "AsterVehicleSupervisor", writes=("VehicleCommand",)),
        Participant("helios_motion_controller", "HeliosMotionController", reads=("VehicleCommand",)),
    ),
)

L02 = Scenario(
    level_id="L02",
    title="Safety alerts are routed away",
    difficulty=1,
    issue_categories=("Partition",),
    topic="SafetyStatus",
    type_name="safety::SafetyStatus",
    expected_writer="aegis_safety_monitor",
    expected_reader="harbor_telemetry_gateway",
    fault="partition",
    participants=(
        Participant("aegis_safety_monitor", "AegisSafetyMonitor", writes=("SafetyStatus",)),
        Participant("harbor_telemetry_gateway", "HarborTelemetryGateway", reads=("SafetyStatus",)),
    ),
)

L03 = Scenario(
    level_id="L03",
    title="Guidance channel has the wrong identity",
    difficulty=2,
    issue_categories=("Topic identity",),
    topic="VehicleCommand",
    type_name="autonomy::VehicleCommand",
    expected_writer="navi_route_planner",
    expected_reader="helios_motion_controller",
    fault="topic_name",
    participants=(
        Participant("navi_route_planner", "NaviRoutePlanner", writes=("VehicleCommand",)),
        Participant("helios_motion_controller", "HeliosMotionController", reads=("VehicleCommand",)),
    ),
)


CATALOG = {scenario.level_id: scenario for scenario in (L01, L02, L03)}
