#!/usr/bin/env python3
"""Explicit live Replay Service GUI launch/shutdown gate for rs_gui_v2."""

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import importlib.util
import json
import os
import signal
import socket
import sys
import time
from typing import Any, Iterable, Mapping, Optional, Tuple


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(APP_DIR, "..", ".."))
SERVICES_DIR = os.path.join(REPO_ROOT, "services")
VENV_PYTHON = os.path.join(REPO_ROOT, "connext_dds_env", "bin", "python")
DEFAULT_OUTPUT = os.path.join(APP_DIR, "live_reports", "replay_service_churn_report.json")


def _reexec_with_repo_venv() -> None:
    if not os.path.isfile(VENV_PYTHON):
        return
    if os.path.realpath(sys.executable) == os.path.realpath(VENV_PYTHON):
        return
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)


_reexec_with_repo_venv()

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


from app_core import AppRuntime  # noqa: E402
from app_core.connext_environment import detect_nddshome, ensure_rti_license  # noqa: E402
from app_core.services import (  # noqa: E402
    RtiServiceAdminClient,
    RtiServiceMonitoringClient,
    ServiceAdminFacade,
    ServiceMonitoringFacade,
    ServiceProcessLaunchState,
    ServiceProcessManager,
    SubprocessServiceProcessSpawner,
    default_rti_service_admin_config,
    default_rti_service_monitoring_config,
)
from gui import (  # noqa: E402
    GuiShellSession,
    GuiShellSessionMode,
    GuiShellSessionFactoryConfig,
    ReplayTabController,
    build_gui_shell_assembly,
)
from gui.main_window import DearPyGuiShell  # noqa: E402
from fakes import FakeDpg  # noqa: E402


@dataclass(frozen=True)
class ReplayServiceChurnConfig:
    admin_domain_id: int = 81
    monitoring_domain_id: int = 81
    data_domain_id: int = 82
    config_name: str = "xcdr"
    database_dir: str = ""
    startup_timeout_sec: float = 10.0
    shutdown_timeout_sec: float = 10.0
    poll_interval_sec: float = 0.1
    require_monitoring_update: bool = True
    output_path: str = DEFAULT_OUTPUT

    def __post_init__(self) -> None:
        object.__setattr__(self, "admin_domain_id", int(self.admin_domain_id))
        object.__setattr__(self, "monitoring_domain_id", int(self.monitoring_domain_id))
        object.__setattr__(self, "data_domain_id", int(self.data_domain_id))
        object.__setattr__(self, "config_name", str(self.config_name).strip() or "xcdr")
        object.__setattr__(self, "database_dir", str(self.database_dir).strip())
        object.__setattr__(self, "startup_timeout_sec", max(0.1, float(self.startup_timeout_sec)))
        object.__setattr__(self, "shutdown_timeout_sec", max(0.1, float(self.shutdown_timeout_sec)))
        object.__setattr__(self, "poll_interval_sec", max(0.01, float(self.poll_interval_sec)))
        object.__setattr__(self, "require_monitoring_update", bool(self.require_monitoring_update))
        object.__setattr__(self, "output_path", str(self.output_path).strip() or DEFAULT_OUTPUT)


@dataclass(frozen=True)
class ReplayServiceChurnResult:
    launch_id: str = ""
    control_name: str = ""
    selected_target_id: str = ""
    pid: Optional[int] = None
    candidate_source: str = ""
    observed_state: str = ""
    monitoring_resource_id: str = ""
    monitoring_service_name: str = ""
    admin_shutdown_ok: bool = False
    process_exit_observed: bool = False
    final_state: str = "unknown"
    returncode: Optional[int] = None
    cleanup_result: Mapping[str, Any] = field(default_factory=dict)
    event_messages: Tuple[str, ...] = field(default_factory=tuple)
    issues: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReplayServiceChurnReport:
    passed: bool
    issues: Tuple[str, ...]
    config: ReplayServiceChurnConfig
    result: ReplayServiceChurnResult
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "config": asdict(self.config),
            "result": asdict(self.result),
            "generated_at": self.generated_at,
        }


def discover_default_database_dir(root: str = REPO_ROOT) -> str:
    log_root = os.path.join(root, "log_dir")
    if not os.path.isdir(log_root):
        return ""
    candidates = []
    for entry in os.listdir(log_root):
        path = os.path.join(log_root, entry)
        if not os.path.isdir(path):
            continue
        if not entry.startswith("recording_"):
            continue
        if not os.path.isfile(os.path.join(path, "metadata.db")):
            continue
        if not os.path.isfile(os.path.join(path, "data_0.db")):
            continue
        candidates.append(path)
    if not candidates:
        return ""
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def evaluate_result(config: ReplayServiceChurnConfig, result: ReplayServiceChurnResult) -> Tuple[str, ...]:
    issues = list(result.issues)
    if not result.launch_id:
        issues.append("launch id was not captured")
    if not result.pid:
        issues.append("Replay Service PID was not observed in GUI state")
    if result.observed_state.lower() not in {"running", "started", "observed", "configured"}:
        issues.append(f"unexpected GUI Replay state: {result.observed_state or 'missing'}")
    if config.require_monitoring_update and not result.monitoring_resource_id:
        issues.append("Replay monitoring update was not observed in controller/session state")
    if not result.admin_shutdown_ok:
        issues.append("GUI close flow did not report successful Replay admin shutdown")
    if not result.process_exit_observed:
        issues.append("GUI close flow did not observe Replay process exit")
    if result.final_state != ServiceProcessLaunchState.EXITED.value:
        issues.append(f"final Replay process state is {result.final_state}")
    return tuple(dict.fromkeys(issues))


async def run_replay_service_churn(config: ReplayServiceChurnConfig) -> ReplayServiceChurnReport:
    executable, database_dir = _live_requirements(config)
    assembly = build_gui_shell_assembly(GuiShellSessionFactoryConfig(
        mode=GuiShellSessionMode.LIVE,
        admin_domain_id=config.admin_domain_id,
        monitoring_domain_id=config.monitoring_domain_id,
        topics_domain_id=config.data_domain_id,
        replay_config_name=config.config_name,
        replay_database_path=database_dir,
        replay_working_dir=REPO_ROOT,
    ))
    session = assembly.session
    runtime = assembly.runtime
    replay_controller = assembly.replay_controller
    replay_manager = assembly.process_manager
    fake = FakeDpg()

    result = ReplayServiceChurnResult()
    try:
        initial_view = await session.next_view_async(process_commands=False)
        shell = DearPyGuiShell(
            view_provider=lambda: initial_view,
            command_sink=session.command_sink,
            close_handler=session.handle_close_request,
            dpg_module=fake,
        )
        shell.render_once()
        launch_callback = _button_callback(fake, "Launch Replay Service")
        launch_callback()

        launch_view = await _wait_for_launch(session, config.startup_timeout_sec, config.poll_interval_sec)
        selected = replay_controller.last_selection.selected_candidate
        launch_id = selected.launch_id if selected is not None else ""
        pid = selected.pid if selected is not None else None
        control_name = selected.service.name if selected is not None else (
            launch_view.replay_tab.selected_target.control_name if launch_view.replay_tab.selected_target is not None else ""
        )
        event_messages = tuple(item.message for item in launch_view.event_log)

        monitoring_resource_id = ""
        monitoring_service_name = ""
        if config.require_monitoring_update:
            monitored = await _wait_for_monitoring(
                replay_controller,
                session,
                config.startup_timeout_sec,
                config.poll_interval_sec,
            )
            if monitored is not None:
                monitoring_resource_id = str(monitored.details.get("resource_id", ""))
                monitoring_service_name = str(monitored.details.get("service_name", ""))

        close_item = f"replay:{launch_id or launch_view.replay_tab.selected_target_id}"
        await session.handle_close_request_async("shutdown_gui_launched", (close_item,))
        cleanup_result, close_events = _close_cleanup_result(runtime)
        final = await _wait_for_final_launch_state(
            replay_manager,
            launch_id,
            config.shutdown_timeout_sec,
            config.poll_interval_sec,
        ) if launch_id else None
        result = ReplayServiceChurnResult(
            launch_id=launch_id,
            control_name=control_name,
            selected_target_id=launch_view.replay_tab.selected_target_id,
            pid=pid,
            candidate_source=(launch_view.replay_tab.selected_target.source if launch_view.replay_tab.selected_target is not None else ""),
            observed_state=launch_view.replay_tab.observed_state,
            monitoring_resource_id=monitoring_resource_id,
            monitoring_service_name=monitoring_service_name,
            admin_shutdown_ok=bool(cleanup_result.get("admin_shutdown_ok", False)),
            process_exit_observed=bool(cleanup_result.get("process_exit_observed", False)),
            final_state=final.state.value if final is not None else "unknown",
            returncode=final.returncode if final is not None else None,
            cleanup_result=dict(cleanup_result),
            event_messages=tuple(dict.fromkeys(event_messages + close_events)),
        )
    finally:
        if result.launch_id:
            final = replay_manager.refresh(result.launch_id)
            pid = final.pid if final is not None else result.pid
            if final is not None and final.alive and pid is not None:
                _kill_pid(pid)
        await _safe_close(assembly.admin_client)
        await _safe_close(assembly.monitoring_client)

    issues = evaluate_result(config, result)
    return ReplayServiceChurnReport(passed=not issues, issues=issues, config=config, result=result)


async def _wait_for_launch(session: GuiShellSession, timeout_sec: float, poll_interval_sec: float):
    deadline = time.monotonic() + timeout_sec
    last_view = await session.next_view_async(process_commands=False)
    while time.monotonic() < deadline:
        last_view = await session.next_view_async()
        selected = last_view.replay_tab.selected_target
        if selected is not None and selected.pid and last_view.replay_tab.observed_state:
            return last_view
        await asyncio.sleep(poll_interval_sec)
    return last_view


async def _wait_for_monitoring(
        replay_controller: ReplayTabController,
        session: GuiShellSession,
        timeout_sec: float,
        poll_interval_sec: float,
) -> Any:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        await session.next_view_async(process_commands=False)
        selected = replay_controller.last_selection.selected_candidate
        if selected is not None and str(selected.details.get("resource_id", "")):
            return selected
        await asyncio.sleep(poll_interval_sec)
    return replay_controller.last_selection.selected_candidate


async def _wait_for_final_launch_state(
        replay_manager: ServiceProcessManager,
        launch_id: str,
        timeout_sec: float,
        poll_interval_sec: float,
):
    deadline = time.monotonic() + timeout_sec
    last_launch = replay_manager.refresh(launch_id)
    while time.monotonic() < deadline:
        last_launch = replay_manager.refresh(launch_id)
        if last_launch is None:
            return None
        if not last_launch.alive or last_launch.state == ServiceProcessLaunchState.EXITED:
            return last_launch
        await asyncio.sleep(poll_interval_sec)
    return last_launch


def _close_cleanup_result(runtime: AppRuntime) -> Tuple[Mapping[str, Any], Tuple[str, ...]]:
    events = runtime.drain_events()
    close_completed = next(
        (event for event in events if event.event_type == "gui.close_completed"),
        None,
    )
    payload = getattr(close_completed, "payload", {}) if close_completed is not None else {}
    cleanup_results = tuple(payload.get("cleanup_results", ()))
    cleanup_result = cleanup_results[0] if cleanup_results else {}
    messages = tuple(
        str(event.payload.get("message", ""))
        for event in events
        if isinstance(getattr(event, "payload", None), dict) and event.payload.get("message")
    )
    return cleanup_result, messages


def write_report(report: ReplayServiceChurnReport, output_path: str) -> None:
    directory = os.path.dirname(os.path.abspath(output_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as report_file:
        json.dump(report.to_dict(), report_file, indent=2, sort_keys=True)
        report_file.write("\n")


def parse_args(argv: Optional[Iterable[str]] = None) -> ReplayServiceChurnConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-domain-id", type=int, default=ReplayServiceChurnConfig.admin_domain_id)
    parser.add_argument("--monitoring-domain-id", type=int, default=ReplayServiceChurnConfig.monitoring_domain_id)
    parser.add_argument("--data-domain-id", type=int, default=ReplayServiceChurnConfig.data_domain_id)
    parser.add_argument("--config-name", default=ReplayServiceChurnConfig.config_name)
    parser.add_argument("--database-dir", default=ReplayServiceChurnConfig.database_dir)
    parser.add_argument("--startup-timeout-sec", type=float, default=ReplayServiceChurnConfig.startup_timeout_sec)
    parser.add_argument("--shutdown-timeout-sec", type=float, default=ReplayServiceChurnConfig.shutdown_timeout_sec)
    parser.add_argument("--poll-interval-sec", type=float, default=ReplayServiceChurnConfig.poll_interval_sec)
    parser.add_argument("--allow-missing-monitoring", action="store_true")
    parser.add_argument("--output", default=ReplayServiceChurnConfig.output_path)
    args = parser.parse_args(tuple(argv) if argv is not None else None)
    return ReplayServiceChurnConfig(
        admin_domain_id=args.admin_domain_id,
        monitoring_domain_id=args.monitoring_domain_id,
        data_domain_id=args.data_domain_id,
        config_name=args.config_name,
        database_dir=args.database_dir,
        startup_timeout_sec=args.startup_timeout_sec,
        shutdown_timeout_sec=args.shutdown_timeout_sec,
        poll_interval_sec=args.poll_interval_sec,
        require_monitoring_update=not args.allow_missing_monitoring,
        output_path=args.output,
    )


def _live_requirements(config: ReplayServiceChurnConfig) -> Tuple[str, str]:
    nddshome = detect_nddshome()
    if not nddshome:
        raise RuntimeError("NDDSHOME or an RTI Connext installation is required")
    if importlib.util.find_spec("rti.connextdds") is None:
        raise RuntimeError("RTI Connext Python API is required")
    if importlib.util.find_spec("rti.request") is None:
        raise RuntimeError("RTI request/reply Python API is required")
    executable = os.path.join(nddshome, "bin", "rtireplayservice")
    if not os.path.isfile(executable):
        raise RuntimeError(f"rtireplayservice not found at {executable}")
    license_file = ensure_rti_license(nddshome)
    if not license_file:
        raise RuntimeError("RTI_LICENSE_FILE or a discoverable RTI license is required")
    for path in (
            os.path.join(SERVICES_DIR, "replay_service_config.xml"),
            os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml"),
    ):
        if not os.path.isfile(path):
            raise RuntimeError(f"required Replay Service config is missing: {path}")
    database_dir = config.database_dir or discover_default_database_dir(REPO_ROOT)
    if not database_dir:
        raise RuntimeError("an existing recording database directory is required")
    if not os.path.isabs(database_dir):
        database_dir = os.path.abspath(database_dir)
    if not os.path.isfile(os.path.join(database_dir, "metadata.db")):
        raise RuntimeError(f"Replay input directory is missing metadata.db: {database_dir}")
    if not os.path.isfile(os.path.join(database_dir, "data_0.db")):
        raise RuntimeError(f"Replay input directory is missing data_0.db: {database_dir}")
    os.environ.setdefault("NDDSHOME", nddshome)
    return executable, database_dir


def _button_callback(fake: FakeDpg, label: str):
    for name, args, kwargs in fake.calls:
        if name != "add_button":
            continue
        button_label = kwargs.get("label") or (args[0] if args else "")
        if button_label == label:
            return kwargs["callback"]
    raise AssertionError(f"Button not rendered: {label}")


async def _safe_close(client: Any) -> None:
    close = getattr(client, "close", None)
    if close is not None:
        await close()


def _kill_pid(pid: int) -> None:
    try:
        os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
    except Exception:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except ProcessLookupError:
            return


def main(argv: Optional[Iterable[str]] = None) -> int:
    config = parse_args(argv)
    report = asyncio.run(run_replay_service_churn(config))
    write_report(report, config.output_path)
    status = "PASS" if report.passed else "FAIL"
    result = report.result
    print(f"{status}: report={config.output_path}")
    print(
        f"control={result.control_name} pid={result.pid} selected={result.selected_target_id} "
        f"observed={result.observed_state} monitoring={result.monitoring_resource_id or 'missing'} "
        f"final={result.final_state} exit={result.returncode}"
    )
    for issue in report.issues:
        print(f"ISSUE: {issue}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())