"""Application assembly helpers for the rs_gui_v2 GUI shell."""

from dataclasses import dataclass, field
from enum import Enum
import socket
import time
from typing import Optional, Tuple

from app_core import AppRuntime, RuntimeConfig
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
from .tabs import RecordTabController, RecordTabControllerConfig


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
        object.__setattr__(self, "mock_pid", int(self.mock_pid))
        object.__setattr__(self, "start_runtime", bool(self.start_runtime))


@dataclass(frozen=True)
class GuiShellAssembly:
    """Objects assembled for a GUI shell session."""

    session: GuiShellSession
    runtime: AppRuntime
    process_manager: ServiceProcessManager
    record_controller: RecordTabController
    admin_client: Optional[FakeServiceAdminClient] = None
    monitoring_client: Optional[FakeServiceMonitoringClient] = None

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
    scheduler = UiFrameScheduler(
        runtime,
        max_event_log=config.event_log_max_size,
        event_drain_limit=config.event_drain_limit,
    )
    session = GuiShellSession(
        runtime=runtime,
        scheduler=scheduler,
        record_controller=controller,
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
        admin_client=admin_client,
        monitoring_client=monitoring_client,
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


def _default_local_hostnames(config: GuiShellSessionFactoryConfig) -> Tuple[str, ...]:
    if config.mode == GuiShellSessionMode.MOCK:
        return (config.mock_hostname,)
    names = {socket.gethostname()}
    fqdn = socket.getfqdn()
    if fqdn:
        names.add(fqdn)
    return tuple(sorted(name for name in names if name))
