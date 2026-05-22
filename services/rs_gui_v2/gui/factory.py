"""Application assembly helpers for the rs_gui_v2 GUI shell."""

from dataclasses import dataclass, field
from enum import Enum
import socket
import time
from typing import Mapping, Optional, Tuple

from app_core import (
    AppRuntime,
    DataSessionSnapshot,
    DiscoveredEndpoint,
    EndpointDirection,
    FakeTopicDiscoveryClient,
    FieldCatalog,
    FieldDescriptor,
    SampleInfoSnapshot,
    RuntimeConfig,
    SampleEnvelope,
    SubscriptionStatus,
    TopicDiscoveryFacade,
    TopicSelection,
    TopicSelectionState,
    TopicSubscriptionRequest,
    TopicSubscriptionState,
    TypeCatalog,
    WorkspacePlotDefinition,
    WorkspacePlotSeries,
    build_plot_buffer_sets,
)
from app_core.services import (
    FakeServiceAdminClient,
    FakeServiceMonitoringClient,
    MonitoringSnapshot,
    MonitoringSnapshotKind,
    ServiceAdminFacade,
    ServiceKind,
    ServiceLaunchIntent,
    ServiceMonitoringFacade,
    ServiceProcessLaunchRequest,
    ServiceProcessManager,
)

from .scheduler import UiFrameScheduler
from .session import GuiShellSession, GuiShellSessionConfig
from .tabs import (
    PlotsTabController,
    PlotsTabControllerConfig,
    RecordTabController,
    RecordTabControllerConfig,
    TopicsTabController,
    TopicsTabControllerConfig,
)


class GuiShellSessionMode(str, Enum):
    """Supported GUI assembly modes."""

    MOCK = "mock"
    HEADLESS = "headless"


@dataclass(frozen=True)
class GuiShellSessionFactoryConfig:
    """Configuration for assembling a default GUI shell session."""

    mode: GuiShellSessionMode = GuiShellSessionMode.MOCK
    workspace_name: str = "Robot Run 03"
    unsaved: bool = False
    command_queue_max_size: int = 100
    event_queue_max_size: int = 500
    event_log_max_size: int = 200
    event_drain_limit: int = 50
    command_drain_limit: Optional[int] = 20
    local_hostnames: Tuple[str, ...] = field(default_factory=tuple)
    recording_label: str = "Recording Service"
    recording_config_name: str = "deploy"
    recording_config_paths: Tuple[str, ...] = (
        "services/recording_service_config.xml",
        "dds/qos/DDS_QOS_PROFILES.xml",
    )
    admin_domain_id: int = 0
    monitoring_domain_id: int = 0
    topics_domain_id: int = 0
    mock_hostname: str = "dev-host"
    mock_pid: int = 4218
    mock_launch_id: str = "launch-recording-main"
    mock_session_guid: str = "8f4f2a1c-0000-4000-8000-000000000000"
    start_runtime: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.mode, GuiShellSessionMode):
            object.__setattr__(self, "mode", GuiShellSessionMode(self.mode))
        object.__setattr__(self, "command_queue_max_size", int(self.command_queue_max_size))
        object.__setattr__(self, "event_queue_max_size", int(self.event_queue_max_size))
        object.__setattr__(self, "event_log_max_size", int(self.event_log_max_size))
        object.__setattr__(self, "event_drain_limit", int(self.event_drain_limit))
        if self.command_drain_limit is not None:
            object.__setattr__(self, "command_drain_limit", int(self.command_drain_limit))
        object.__setattr__(self, "local_hostnames", tuple(str(name) for name in self.local_hostnames))
        object.__setattr__(self, "recording_config_paths", tuple(str(path) for path in self.recording_config_paths))
        object.__setattr__(self, "admin_domain_id", int(self.admin_domain_id))
        object.__setattr__(self, "monitoring_domain_id", int(self.monitoring_domain_id))
        object.__setattr__(self, "topics_domain_id", int(self.topics_domain_id))
        object.__setattr__(self, "mock_pid", int(self.mock_pid))
        object.__setattr__(self, "start_runtime", bool(self.start_runtime))


@dataclass(frozen=True)
class GuiShellAssembly:
    """Objects assembled for a GUI shell session."""

    session: GuiShellSession
    runtime: AppRuntime
    process_manager: ServiceProcessManager
    record_controller: RecordTabController
    topics_controller: TopicsTabController
    plots_controller: PlotsTabController
    admin_client: Optional[FakeServiceAdminClient] = None
    monitoring_client: Optional[FakeServiceMonitoringClient] = None
    discovery_client: Optional[FakeTopicDiscoveryClient] = None

    def shell(self, dpg_module=None):
        """Create a Dear PyGui shell using this assembly's session wiring."""

        from .main_window import DearPyGuiShell
        return DearPyGuiShell(
            view_provider=self.session.next_view,
            command_sink=self.session.command_sink,
            dpg_module=dpg_module,
        )


def build_default_gui_shell_session(
        config: Optional[GuiShellSessionFactoryConfig] = None,
) -> GuiShellSession:
    """Build the default GUI shell session and return only the session."""

    return build_gui_shell_assembly(config).session


def build_gui_shell_assembly(
        config: Optional[GuiShellSessionFactoryConfig] = None,
) -> GuiShellAssembly:
    """Assemble runtime, services, controller, scheduler, and GUI session."""

    config = config or GuiShellSessionFactoryConfig()
    runtime = AppRuntime(RuntimeConfig(
        command_queue_max_size=config.command_queue_max_size,
        event_queue_max_size=config.event_queue_max_size,
    ))
    if config.start_runtime:
        runtime.start()

    local_hostnames = config.local_hostnames or _default_local_hostnames(config)
    admin_client = FakeServiceAdminClient() if config.mode == GuiShellSessionMode.MOCK else None
    monitoring_client = FakeServiceMonitoringClient() if config.mode == GuiShellSessionMode.MOCK else None
    admin_facade = ServiceAdminFacade(admin_client) if admin_client is not None else None
    monitoring_facade = ServiceMonitoringFacade(monitoring_client) if monitoring_client is not None else None
    discovery_client = _mock_discovery_client(config) if config.mode == GuiShellSessionMode.MOCK else None
    discovery_facade = (
        TopicDiscoveryFacade(discovery_client, selections=_mock_topic_selections(config))
        if discovery_client is not None else None
    )
    data_session_snapshot_provider = (
        _mock_data_session_snapshot_provider(config)
        if config.mode == GuiShellSessionMode.MOCK else None
    )

    process_manager = ServiceProcessManager(
        spawner=_MockServiceProcessSpawner(config.mock_pid) if config.mode == GuiShellSessionMode.MOCK else None,
        hostname=config.mock_hostname if config.mode == GuiShellSessionMode.MOCK else None,
        clock=time.time,
    )
    if config.mode == GuiShellSessionMode.MOCK:
        launch = process_manager.launch(
            _mock_recording_launch_request(config),
            launch_id=config.mock_launch_id,
            session_guid=config.mock_session_guid,
        )
        if monitoring_client is not None:
            monitoring_client.push_snapshot(_mock_monitoring_snapshot(config, launch.identity.service_ref))

    controller = RecordTabController(
        process_manager,
        admin_facade=admin_facade,
        monitoring_facade=monitoring_facade,
        config=RecordTabControllerConfig(
            display_label=config.recording_label,
            local_hostnames=local_hostnames,
        ),
    )
    topics_controller = TopicsTabController(
        discovery_facade=discovery_facade,
        field_catalogs=_mock_topic_field_catalogs() if config.mode == GuiShellSessionMode.MOCK else {},
        data_session_snapshot_provider=data_session_snapshot_provider,
        config=TopicsTabControllerConfig(
            domain_id=config.topics_domain_id,
            selected_topic_key=f"{config.topics_domain_id}:RobotTelemetry" if config.mode == GuiShellSessionMode.MOCK else "",
        ),
    )
    plots_controller = PlotsTabController(
        data_session_snapshot_provider=data_session_snapshot_provider,
        config=PlotsTabControllerConfig(
            selected_plot_name="Robot Motion" if config.mode == GuiShellSessionMode.MOCK else "",
        ),
    )
    scheduler = UiFrameScheduler(
        runtime,
        max_event_log=config.event_log_max_size,
        event_drain_limit=config.event_drain_limit,
    )
    session = GuiShellSession(
        runtime=runtime,
        scheduler=scheduler,
        record_controller=controller,
        topics_controller=topics_controller,
        plots_controller=plots_controller,
        config=GuiShellSessionConfig(
            workspace_name=config.workspace_name,
            unsaved=config.unsaved,
            command_drain_limit=config.command_drain_limit,
            local_hostnames=local_hostnames,
        ),
    )
    return GuiShellAssembly(
        session=session,
        runtime=runtime,
        process_manager=process_manager,
        record_controller=controller,
        topics_controller=topics_controller,
        plots_controller=plots_controller,
        admin_client=admin_client,
        monitoring_client=monitoring_client,
        discovery_client=discovery_client,
    )


class _MockServiceProcessHandle:
    def __init__(self, pid: int) -> None:
        self.pid = int(pid)
        self.returncode = None
        self.terminate_calls = 0

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1


class _MockServiceProcessSpawner:
    def __init__(self, pid: int) -> None:
        self.handle = _MockServiceProcessHandle(pid)
        self.command_lines = []

    def start(self, command_line, working_dir: str = "", environment=None):
        self.command_lines.append(tuple(command_line))
        return self.handle


def _mock_recording_launch_request(config: GuiShellSessionFactoryConfig) -> ServiceProcessLaunchRequest:
    return ServiceProcessLaunchRequest(
        intent=ServiceLaunchIntent(
            kind=ServiceKind.RECORDING,
            label=config.recording_label,
            admin_domain_id=config.admin_domain_id,
            monitoring_domain_id=config.monitoring_domain_id,
            config_paths=config.recording_config_paths,
        ),
        config_name=config.recording_config_name,
        executable="rtirecordingservice",
    )


def _mock_monitoring_snapshot(
        config: GuiShellSessionFactoryConfig,
        service,
) -> MonitoringSnapshot:
    return MonitoringSnapshot(
        service=service,
        kind=MonitoringSnapshotKind.CONFIG,
        state="RUNNING",
        metrics={"cpu_percent": 2.0, "memory_mb": 180, "throughput": "1.2 MB/s"},
        details={
            "application_guid": "mock-recording-app-guid",
            "process_id": config.mock_pid,
            "host_name": config.mock_hostname,
            "sessions": 1,
            "topics": 4,
            "last_event": "monitoring active",
        },
        observed_at=time.time(),
    )


def _mock_discovery_client(config: GuiShellSessionFactoryConfig) -> FakeTopicDiscoveryClient:
    catalog = TypeCatalog()
    catalog.register_type("Robot::Telemetry", source="dds/datamodel/xml_gen/RobotTelemetry.xml", kind="struct")
    catalog.register_type(
        "RTI::Service::Monitoring::Periodic",
        source="built-in monitoring XML",
        kind="struct",
    )
    client = FakeTopicDiscoveryClient(type_catalog=catalog)
    now = time.time()
    for endpoint in (
            DiscoveredEndpoint(
                domain_id=config.topics_domain_id,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                direction=EndpointDirection.WRITER,
                endpoint_key="robot-telemetry-writer",
                participant_key="participant-robot-publisher",
                participant_name="robot_state_publisher",
                partitions=("/robot/alpha",),
                observed_at=now - 2,
            ),
            DiscoveredEndpoint(
                domain_id=config.topics_domain_id,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                direction=EndpointDirection.READER,
                endpoint_key="robot-telemetry-reader",
                participant_key="participant-gui-reader",
                participant_name="rs_gui_v2",
                partitions=("/robot/alpha",),
                observed_at=now - 1,
            ),
            DiscoveredEndpoint(
                domain_id=config.topics_domain_id,
                topic_name="CameraStatus",
                type_name="Camera::Status",
                direction=EndpointDirection.WRITER,
                endpoint_key="camera-status-writer",
                participant_key="participant-camera",
                participant_name="camera_driver",
                partitions=("/sensors",),
                observed_at=now - 8,
            ),
            DiscoveredEndpoint(
                domain_id=config.topics_domain_id,
                topic_name="rti/service/monitoring/periodic",
                type_name="RTI::Service::Monitoring::Periodic",
                direction=EndpointDirection.WRITER,
                endpoint_key="service-monitoring-writer",
                participant_key="participant-recording-service",
                participant_name="recording_service_8f4f2a1c",
                observed_at=now - 1,
            ),
    ):
        client.apply(endpoint)
    return client


def _mock_topic_selections(config: GuiShellSessionFactoryConfig) -> TopicSelectionState:
    return TopicSelectionState().select(TopicSelection(
        domain_id=config.topics_domain_id,
        topic_name="RobotTelemetry",
        type_name="Robot::Telemetry",
        selected_fields=("pose.x", "pose.y", "velocity"),
        plot_fields=("velocity",),
        created_at=time.time() - 60,
        updated_at=time.time() - 10,
    ))


def _mock_topic_field_catalogs() -> Mapping[str, FieldCatalog]:
    return {
        "Robot::Telemetry": FieldCatalog(
            type_name="Robot::Telemetry",
            fields=(
                FieldDescriptor("pose", "pose", "Robot::Pose", "struct", "struct", depth=0),
                FieldDescriptor("pose.x", "x", "float64", "float64", "float", parent_path="pose", depth=1),
                FieldDescriptor("pose.y", "y", "float64", "float64", "float", parent_path="pose", depth=1),
                FieldDescriptor("velocity", "velocity", "float32", "float32", "float", depth=0),
                FieldDescriptor("mode", "mode", "Robot::Mode", "enum", "enum", depth=0),
            ),
        ),
    }


def _mock_topic_subscription_request(config: GuiShellSessionFactoryConfig) -> TopicSubscriptionRequest:
    return TopicSubscriptionRequest(
        domain_id=config.topics_domain_id,
        topic_name="RobotTelemetry",
        type_name="Robot::Telemetry",
        selected_fields=("pose.x", "pose.y", "velocity"),
        max_samples=256,
    )


def _mock_topic_subscription_states(config: GuiShellSessionFactoryConfig) -> Tuple[TopicSubscriptionState, ...]:
    return (TopicSubscriptionState(
        request=_mock_topic_subscription_request(config),
        status=SubscriptionStatus.RECEIVING,
        received_samples=42,
        updated_at=time.time(),
    ),)


def _mock_data_session_snapshot_provider(config: GuiShellSessionFactoryConfig):
    snapshot = DataSessionSnapshot(
        workspace_name=config.workspace_name,
        subscriptions=_mock_topic_subscription_states(config),
        samples={_mock_topic_subscription_request(config).key: _mock_topic_samples(config)},
        plots=_mock_plot_snapshots(config),
        updated_at=time.time(),
    )

    def _provider() -> DataSessionSnapshot:
        return snapshot
    return _provider


def _mock_topic_samples(config: GuiShellSessionFactoryConfig) -> Tuple[SampleEnvelope, ...]:
    request = _mock_topic_subscription_request(config)
    return (SampleEnvelope(
        subscription_key=request.key,
        domain_id=config.topics_domain_id,
        topic_name="RobotTelemetry",
        type_name="Robot::Telemetry",
        data={"pose": {"x": 12.5, "y": -3.25}, "velocity": 1.7, "mode": "AUTO"},
        observed_at=time.time(),
    ),)


def _mock_plot_snapshots(config: GuiShellSessionFactoryConfig):
    plot = WorkspacePlotDefinition(
        name="Robot Motion",
        history_seconds=30.0,
        max_points=512,
        series=(
            WorkspacePlotSeries(
                domain_id=config.topics_domain_id,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                field_path="velocity",
                label="Velocity",
            ),
            WorkspacePlotSeries(
                domain_id=config.topics_domain_id,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                field_path="pose.x",
                label="Pose X",
            ),
        ),
    )
    buffers = build_plot_buffer_sets((plot,), min_interval_seconds=0.25)
    request = _mock_topic_subscription_request(config)
    now = time.time()
    for offset, pose_x, velocity in (
            (6.0, 10.8, 1.2),
            (4.0, 11.4, 1.35),
            (2.0, 12.5, 1.7),
            (0.0, 13.1, 1.55),
    ):
        sample = SampleEnvelope(
            subscription_key=request.key,
            domain_id=config.topics_domain_id,
            topic_name="RobotTelemetry",
            type_name="Robot::Telemetry",
            data={"pose": {"x": pose_x, "y": -3.25}, "velocity": velocity, "mode": "AUTO"},
            info=SampleInfoSnapshot(source_timestamp=now - offset),
            observed_at=now - offset,
        )
        for buffer in buffers:
            buffer.update_from_sample(sample)
    return tuple(buffer.snapshot() for buffer in buffers)


def _default_local_hostnames(config: GuiShellSessionFactoryConfig) -> Tuple[str, ...]:
    if config.mode == GuiShellSessionMode.MOCK:
        return (config.mock_hostname,)
    names = {socket.gethostname()}
    fqdn = socket.getfqdn()
    if fqdn:
        names.add(fqdn)
    return tuple(sorted(name for name in names if name))
