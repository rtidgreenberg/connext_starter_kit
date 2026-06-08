#!/usr/bin/env python3
"""Live Recording Service restart/churn gate for rs_gui_v2."""

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
import os
import sys
import time
import uuid
from typing import Any, Iterable, List, Mapping, Optional, Tuple


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(APP_DIR, "..", ".."))
SERVICES_DIR = os.path.join(REPO_ROOT, "services")
VENV_PYTHON = os.path.join(REPO_ROOT, "connext_dds_env", "bin", "python")
DEFAULT_OUTPUT = os.path.join(APP_DIR, "live_reports", "service_churn_report.json")


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


from app_core.connext_environment import detect_nddshome, ensure_rti_license  # noqa: E402
from app_core.events import CommandStatus  # noqa: E402
from app_core.services import (  # noqa: E402
    AdminReadiness,
    ServiceAdminFacade,
    ServiceCommand,
    ServiceInstanceRef,
    ServiceKind,
    ServiceLaunchIntent,
    ServiceProcessLaunchRequest,
    ServiceProcessLaunchState,
    ServiceProcessManager,
    ServiceProcessTerminationStatus,
)
from app_core.services.rti_admin import (  # noqa: E402
    RtiServiceAdminClient,
    RtiServiceAdminConfig,
    default_rti_service_admin_config,
)


@dataclass(frozen=True)
class ServiceChurnConfig:
    """CLI-configurable inputs for the live service churn gate."""

    iterations: int = 2
    admin_domain_id: int = 61
    monitoring_domain_id: int = 62
    data_domain_id: int = 63
    config_name: str = "deploy"
    admin_resource_name: str = "deploy"
    startup_timeout_sec: float = 8.0
    shutdown_timeout_sec: float = 8.0
    poll_interval_sec: float = 0.25
    reply_timeout_sec: float = 2.0
    require_admin_ready: bool = True
    require_admin_shutdown: bool = False
    output_path: str = DEFAULT_OUTPUT

    def __post_init__(self) -> None:
        object.__setattr__(self, "iterations", max(1, int(self.iterations)))
        object.__setattr__(self, "admin_domain_id", int(self.admin_domain_id))
        object.__setattr__(self, "monitoring_domain_id", int(self.monitoring_domain_id))
        object.__setattr__(self, "data_domain_id", int(self.data_domain_id))
        object.__setattr__(self, "startup_timeout_sec", max(0.1, float(self.startup_timeout_sec)))
        object.__setattr__(self, "shutdown_timeout_sec", max(0.1, float(self.shutdown_timeout_sec)))
        object.__setattr__(self, "poll_interval_sec", max(0.01, float(self.poll_interval_sec)))
        object.__setattr__(self, "reply_timeout_sec", max(0.1, float(self.reply_timeout_sec)))


@dataclass(frozen=True)
class ChurnIterationResult:
    """One launch/shutdown cycle result."""

    iteration: int
    launch_id: str
    control_name: str
    pid: Optional[int]
    command_line: Tuple[str, ...]
    admin_resource_name: str
    readiness: Optional[Mapping[str, Any]] = None
    admin_shutdown_status: str = "not_attempted"
    admin_shutdown_message: str = ""
    termination_status: str = "not_attempted"
    final_state: str = "unknown"
    returncode: Optional[int] = None
    elapsed_sec: float = 0.0
    issues: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ServiceChurnReport:
    """Serializable report for live service churn validation."""

    passed: bool
    issues: Tuple[str, ...]
    config: ServiceChurnConfig
    iterations: Tuple[ChurnIterationResult, ...]
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "config": asdict(self.config),
            "iterations": [asdict(iteration) for iteration in self.iterations],
            "generated_at": self.generated_at,
        }


async def run_service_churn(config: ServiceChurnConfig) -> ServiceChurnReport:
    prepare_connext_environment()
    manager = ServiceProcessManager()
    admin_client = RtiServiceAdminClient(config=_admin_config(config))
    admin_facade = ServiceAdminFacade(admin_client)
    results: List[ChurnIterationResult] = []
    try:
        for index in range(config.iterations):
            results.append(await run_iteration(config, manager, admin_facade, index))
    finally:
        await _safe_admin_close(admin_client)

    issues = list(evaluate_churn(config, results))
    return ServiceChurnReport(
        passed=not issues,
        issues=tuple(issues),
        config=config,
        iterations=tuple(results),
    )


async def run_iteration(
        config: ServiceChurnConfig,
        manager: ServiceProcessManager,
        admin_facade: ServiceAdminFacade,
        iteration: int,
) -> ChurnIterationResult:
    started = time.monotonic()
    request = build_launch_request(config, iteration)
    launch_id = f"churn-{iteration}-{uuid.uuid4().hex[:8]}"
    launch = manager.launch(request, launch_id=launch_id)
    issues: List[str] = []
    readiness: Optional[AdminReadiness] = None
    admin_status = "not_attempted"
    admin_message = ""
    termination_status = "not_attempted"
    admin_resource_name = config.admin_resource_name or launch.request.config_name

    if launch.state == ServiceProcessLaunchState.START_FAILED:
        issues.append(f"launch failed: {launch.message}")
    else:
        refreshed = await wait_for_state(
            manager,
            launch.launch_id,
            alive=True,
            timeout_sec=config.startup_timeout_sec,
            poll_interval_sec=config.poll_interval_sec,
        )
        if refreshed is None or not refreshed.alive:
            issues.append("process exited before admin readiness")
        else:
            readiness = await wait_for_admin_readiness(config, admin_facade, launch.identity.service_ref)
            if config.require_admin_ready and (readiness is None or not readiness.ready):
                message = readiness.message if readiness is not None else "readiness check failed"
                issues.append(f"admin readiness failed: {message}")

        try:
            outcome = await admin_facade.execute(
                launch.identity.service_ref,
                ServiceCommand.SHUTDOWN,
                parameters={"admin_resource_name": admin_resource_name},
                timeout_sec=config.reply_timeout_sec,
            )
            admin_status = outcome.status.value
            admin_message = outcome.message
            if config.require_admin_shutdown and outcome.status != CommandStatus.ACKNOWLEDGED:
                issues.append(f"admin shutdown was not acknowledged: {outcome.status.value} {outcome.message}")
        except Exception as exc:
            admin_status = "error"
            admin_message = str(exc)
            if config.require_admin_shutdown:
                issues.append(f"admin shutdown failed: {exc}")

        exited = await wait_for_exit(
            manager,
            launch.launch_id,
            timeout_sec=config.shutdown_timeout_sec,
            poll_interval_sec=config.poll_interval_sec,
        )
        if exited is None or exited.alive:
            termination_status = request_local_termination(manager, launch.identity.service_ref, launch.launch_id)
            exited = await wait_for_exit(
                manager,
                launch.launch_id,
                timeout_sec=config.shutdown_timeout_sec,
                poll_interval_sec=config.poll_interval_sec,
            )
            if exited is None or exited.alive:
                termination_status = force_kill(manager, launch.launch_id) or termination_status
                exited = await wait_for_exit(
                    manager,
                    launch.launch_id,
                    timeout_sec=max(1.0, config.poll_interval_sec),
                    poll_interval_sec=config.poll_interval_sec,
                )
        else:
            termination_status = "exited_after_admin_shutdown"

        if exited is None or exited.alive:
            issues.append("process did not exit after shutdown and fallback termination")

    final = manager.refresh(launch.launch_id) or launch
    return ChurnIterationResult(
        iteration=iteration,
        launch_id=launch.launch_id,
        control_name=launch.identity.service_ref.name,
        pid=launch.pid,
        command_line=launch.command_line,
        admin_resource_name=admin_resource_name,
        readiness=readiness.to_dict() if readiness is not None else None,
        admin_shutdown_status=admin_status,
        admin_shutdown_message=admin_message,
        termination_status=termination_status,
        final_state=final.state.value,
        returncode=final.returncode,
        elapsed_sec=time.monotonic() - started,
        issues=tuple(issues),
    )


def build_launch_request(config: ServiceChurnConfig, iteration: int) -> ServiceProcessLaunchRequest:
    nddshome = os.environ.get("NDDSHOME", detect_nddshome())
    service_config = os.path.join(SERVICES_DIR, "recording_service_config.xml")
    qos_file = os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml")
    run_dir = os.path.join(REPO_ROOT, "test_output", "rs_gui_v2", "service_churn", f"run_{iteration}")
    os.makedirs(run_dir, exist_ok=True)
    return ServiceProcessLaunchRequest(
        intent=ServiceLaunchIntent(
            kind=ServiceKind.RECORDING,
            label=f"rs gui v2 churn {iteration}",
            admin_domain_id=config.admin_domain_id,
            monitoring_domain_id=config.monitoring_domain_id,
            config_paths=(service_config, qos_file),
        ),
        config_name=config.config_name,
        executable=os.path.join(nddshome, "bin", "rtirecordingservice"),
        working_dir=run_dir,
        verbosity="ERROR:ERROR",
        environment={
            "NDDSHOME": nddshome,
            "RTI_LICENSE_FILE": os.environ.get("RTI_LICENSE_FILE", ""),
            "DOMAIN_ID": str(config.data_domain_id),
            "ADMIN_DOMAIN_ID": str(config.admin_domain_id),
        },
        extra_args=(
            f"-DDOMAIN_ID={config.data_domain_id}",
            f"-DADMIN_DOMAIN_ID={config.admin_domain_id}",
        ),
    )


async def wait_for_admin_readiness(
        config: ServiceChurnConfig,
        admin_facade: ServiceAdminFacade,
        service: ServiceInstanceRef,
) -> Optional[AdminReadiness]:
    deadline = time.monotonic() + config.startup_timeout_sec
    readiness = None
    while time.monotonic() < deadline:
        try:
            readiness = await admin_facade.readiness(service)
        except Exception:
            readiness = None
        if readiness is not None and readiness.ready:
            return readiness
        await asyncio.sleep(config.poll_interval_sec)
    return readiness


async def wait_for_state(
        manager: ServiceProcessManager,
        launch_id: str,
        alive: bool,
        timeout_sec: float,
        poll_interval_sec: float,
):
    deadline = time.monotonic() + timeout_sec
    current = manager.refresh(launch_id)
    while time.monotonic() < deadline:
        current = manager.refresh(launch_id)
        if current is None:
            return None
        if current.alive == alive:
            return current
        await asyncio.sleep(poll_interval_sec)
    return current


async def wait_for_exit(
        manager: ServiceProcessManager,
        launch_id: str,
        timeout_sec: float,
        poll_interval_sec: float,
):
    return await wait_for_state(manager, launch_id, alive=False, timeout_sec=timeout_sec, poll_interval_sec=poll_interval_sec)


def request_local_termination(manager: ServiceProcessManager, service: ServiceInstanceRef, launch_id: str) -> str:
    selection = manager.candidate_selection(service, selected_candidate_id=launch_id)
    outcome = manager.request_local_termination(
        selection,
        graceful_shutdown_failed=True,
        candidate_id=launch_id,
    )
    return outcome.status.value


def force_kill(manager: ServiceProcessManager, launch_id: str) -> str:
    handle = getattr(manager, "_handles", {}).get(launch_id)
    kill = getattr(handle, "kill", None)
    if kill is None:
        return "kill_unavailable"
    kill()
    return "kill_requested"


def evaluate_churn(
        config: ServiceChurnConfig,
        iterations: Iterable[ChurnIterationResult],
) -> Tuple[str, ...]:
    results = tuple(iterations)
    issues: List[str] = []
    if len(results) != config.iterations:
        issues.append(f"completed {len(results)} iteration(s), expected {config.iterations}")
    names = [result.control_name for result in results]
    if len(set(names)) != len(names):
        issues.append("control names were reused across churn iterations")
    for result in results:
        issues.extend(f"iteration {result.iteration}: {issue}" for issue in result.issues)
        if result.final_state not in (ServiceProcessLaunchState.EXITED.value, ServiceProcessLaunchState.START_FAILED.value):
            issues.append(f"iteration {result.iteration}: final state is {result.final_state}")
        if config.require_admin_ready:
            readiness = result.readiness or {}
            if readiness.get("status") != "ready":
                issues.append(f"iteration {result.iteration}: admin readiness status is {readiness.get('status', 'missing')}")
        if config.require_admin_shutdown and result.admin_shutdown_status != CommandStatus.ACKNOWLEDGED.value:
            issues.append(f"iteration {result.iteration}: admin shutdown status is {result.admin_shutdown_status}")
    return tuple(dict.fromkeys(issues))


def write_report(report: ServiceChurnReport, output_path: str) -> None:
    directory = os.path.dirname(os.path.abspath(output_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as report_file:
        json.dump(report.to_dict(), report_file, indent=2, sort_keys=True)
        report_file.write("\n")


def parse_args(argv: Optional[Iterable[str]] = None) -> ServiceChurnConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=ServiceChurnConfig.iterations)
    parser.add_argument("--admin-domain-id", type=int, default=ServiceChurnConfig.admin_domain_id)
    parser.add_argument("--monitoring-domain-id", type=int, default=ServiceChurnConfig.monitoring_domain_id)
    parser.add_argument("--data-domain-id", type=int, default=ServiceChurnConfig.data_domain_id)
    parser.add_argument("--config-name", default=ServiceChurnConfig.config_name)
    parser.add_argument("--admin-resource-name", default=ServiceChurnConfig.admin_resource_name)
    parser.add_argument("--startup-timeout-sec", type=float, default=ServiceChurnConfig.startup_timeout_sec)
    parser.add_argument("--shutdown-timeout-sec", type=float, default=ServiceChurnConfig.shutdown_timeout_sec)
    parser.add_argument("--poll-interval-sec", type=float, default=ServiceChurnConfig.poll_interval_sec)
    parser.add_argument("--reply-timeout-sec", type=float, default=ServiceChurnConfig.reply_timeout_sec)
    parser.add_argument("--allow-admin-unready", action="store_true")
    parser.add_argument("--require-admin-shutdown", action="store_true")
    parser.add_argument("--output", default=ServiceChurnConfig.output_path)
    args = parser.parse_args(tuple(argv) if argv is not None else None)
    return ServiceChurnConfig(
        iterations=args.iterations,
        admin_domain_id=args.admin_domain_id,
        monitoring_domain_id=args.monitoring_domain_id,
        data_domain_id=args.data_domain_id,
        config_name=args.config_name,
        admin_resource_name=args.admin_resource_name,
        startup_timeout_sec=args.startup_timeout_sec,
        shutdown_timeout_sec=args.shutdown_timeout_sec,
        poll_interval_sec=args.poll_interval_sec,
        reply_timeout_sec=args.reply_timeout_sec,
        require_admin_ready=not args.allow_admin_unready,
        require_admin_shutdown=args.require_admin_shutdown,
        output_path=args.output,
    )


def prepare_connext_environment() -> None:
    nddshome = detect_nddshome()
    if nddshome and not os.environ.get("NDDSHOME"):
        os.environ["NDDSHOME"] = nddshome
    ensure_rti_license(nddshome)


def _admin_config(config: ServiceChurnConfig) -> RtiServiceAdminConfig:
    base = default_rti_service_admin_config()
    return RtiServiceAdminConfig(
        xml_types_dir=base.xml_types_dir,
        qos_file=base.qos_file,
        discovery_timeout_sec=min(config.poll_interval_sec, config.reply_timeout_sec),
        discovery_poll_sec=config.poll_interval_sec,
        reply_timeout_sec=config.reply_timeout_sec,
    )


async def _safe_admin_close(admin_client: Any) -> None:
    close = getattr(admin_client, "close", None)
    if close is not None:
        await close()


def main(argv: Optional[Iterable[str]] = None) -> int:
    config = parse_args(argv)
    report = asyncio.run(run_service_churn(config))
    write_report(report, config.output_path)
    status = "PASS" if report.passed else "FAIL"
    print(f"{status}: iterations={len(report.iterations)} report={config.output_path}")
    for result in report.iterations:
        print(
            f"iteration={result.iteration} control={result.control_name} "
            f"pid={result.pid} final={result.final_state} admin={result.admin_shutdown_status} "
            f"termination={result.termination_status}"
        )
    for issue in report.issues:
        print(f"ISSUE: {issue}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())