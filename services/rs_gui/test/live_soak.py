#!/usr/bin/env python3
"""Live DDS smoke/soak gate for rs_gui_v2 DynamicData subscriptions."""

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
import os
import resource
import sys
import time
from typing import Any, Iterable, List, Mapping, Optional, Tuple


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(APP_DIR, "..", ".."))
VENV_PYTHON = os.path.join(REPO_ROOT, "connext_dds_env", "bin", "python")
DEFAULT_OUTPUT = os.path.join(APP_DIR, "live_reports", "live_soak_report.json")


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


from app_core import (  # noqa: E402
    AppRuntime,
    DataSessionConfig,
    DataSessionCoordinator,
    RuntimeCounters,
    TopicSubscriptionRequest,
    TypeCatalog,
    WorkspaceDocument,
    WorkspacePlotDefinition,
    WorkspacePlotSeries,
)
from app_core.rti_subscriptions import (  # noqa: E402
    RtiSubscriptionClient,
    RtiSubscriptionConfig,
)
from app_core.connext_environment import detect_nddshome, ensure_rti_license  # noqa: E402
from app_core.rti_types import DynamicTypeLookup  # noqa: E402
from app_core.types import TypeResolution  # noqa: E402


@dataclass(frozen=True)
class LiveSoakConfig:
    """CLI-configurable parameters for the live soak gate."""

    domain_id: int = 0
    topic_name: str = "RsGuiV2SoakTelemetry"
    type_name: str = "RsGuiV2SoakTelemetryType"
    duration_sec: float = 10.0
    warmup_sec: float = 0.5
    poll_interval_sec: float = 0.05
    publish_rate_hz: float = 100.0
    max_samples: int = 256
    plot_max_points: int = 512
    reader_history_depth: int = 128
    reader_take_max_samples: int = 128
    min_samples: int = 1
    memory_growth_limit_mb: float = 256.0
    start_publisher: bool = True
    output_path: str = DEFAULT_OUTPUT

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "duration_sec", max(0.1, float(self.duration_sec)))
        object.__setattr__(self, "warmup_sec", max(0.0, float(self.warmup_sec)))
        object.__setattr__(self, "poll_interval_sec", max(0.001, float(self.poll_interval_sec)))
        object.__setattr__(self, "publish_rate_hz", max(0.0, float(self.publish_rate_hz)))
        object.__setattr__(self, "max_samples", max(1, int(self.max_samples)))
        object.__setattr__(self, "plot_max_points", max(1, int(self.plot_max_points)))
        object.__setattr__(self, "reader_history_depth", max(1, int(self.reader_history_depth)))
        object.__setattr__(self, "reader_take_max_samples", max(1, int(self.reader_take_max_samples)))
        object.__setattr__(self, "min_samples", max(0, int(self.min_samples)))
        object.__setattr__(self, "memory_growth_limit_mb", max(0.0, float(self.memory_growth_limit_mb)))


@dataclass(frozen=True)
class LiveSoakMetrics:
    """Measured result from one live soak run."""

    samples_received: int = 0
    samples_dropped: int = 0
    cached_samples: int = 0
    plot_points: int = 0
    published_samples: int = 0
    poll_count: int = 0
    elapsed_sec: float = 0.0
    rss_start_kb: int = 0
    rss_end_kb: int = 0
    errors: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def rss_growth_kb(self) -> int:
        return max(0, int(self.rss_end_kb) - int(self.rss_start_kb))


@dataclass(frozen=True)
class LiveSoakReport:
    """Serializable pass/fail report for CI and manual operator runs."""

    passed: bool
    issues: Tuple[str, ...]
    config: LiveSoakConfig
    metrics: LiveSoakMetrics
    counters: Mapping[str, int]
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "config": asdict(self.config),
            "metrics": asdict(self.metrics),
            "counters": dict(self.counters),
            "generated_at": self.generated_at,
        }


class InMemoryTelemetryTypeRegistry:
    """Tiny registry that gives RtiSubscriptionClient an in-memory DynamicType."""

    def __init__(self, type_name: str, dynamic_type: Any) -> None:
        self.type_name = type_name
        self.dynamic_type = dynamic_type

    def lookup(self, type_name: str) -> DynamicTypeLookup:
        if type_name != self.type_name:
            return DynamicTypeLookup(
                resolution=TypeResolution(
                    type_name=type_name,
                    status="missing",
                    message=f"live soak type is {self.type_name}, not {type_name}",
                )
            )
        return DynamicTypeLookup(
            resolution=TypeResolution(
                type_name=type_name,
                status="available",
                source="in-memory-live-soak",
                kind="struct",
                candidates=(type_name,),
            ),
            dynamic_type=self.dynamic_type,
        )


class LiveTelemetryPublisher:
    """Built-in DynamicData publisher used by the live soak gate."""

    def __init__(self, dds: Any, config: LiveSoakConfig, dynamic_type: Any) -> None:
        self._dds = dds
        self._config = config
        self._dynamic_type = dynamic_type
        self._participant = dds.DomainParticipant(config.domain_id)
        self._topic = dds.DynamicData.Topic(self._participant, config.topic_name, dynamic_type)
        self._writer = self._create_writer()
        self._published = 0

    @property
    def published(self) -> int:
        return self._published

    def publish_until(self, target_count: int) -> None:
        while self._published < target_count:
            sample = self._writer.create_data()
            sample["source_id"] = "rs-gui-v2-soak"
            sample["index"] = self._published
            sample["value"] = float(self._published)
            self._writer.write(sample)
            self._published += 1

    def close(self) -> None:
        _safe_close(self._writer)
        try:
            close_contained = getattr(self._participant, "close_contained_entities", None)
            if close_contained is not None:
                close_contained()
        finally:
            _safe_close(self._participant)

    def _create_writer(self) -> Any:
        writer_qos = bounded_dynamic_data_writer_qos(
            self._dds,
            history_depth=self._config.reader_history_depth,
            max_samples=self._config.reader_history_depth,
            max_instances=1,
            max_samples_per_instance=self._config.reader_history_depth,
        )
        publisher = getattr(self._participant, "implicit_publisher", self._participant)
        return self._dds.DynamicData.DataWriter(publisher, self._topic, writer_qos)


def build_live_soak_workspace(config: LiveSoakConfig) -> WorkspaceDocument:
    return WorkspaceDocument(
        name="rs_gui_v2 live soak",
        domains=(config.domain_id,),
        subscriptions=(TopicSubscriptionRequest(
            domain_id=config.domain_id,
            topic_name=config.topic_name,
            type_name=config.type_name,
            selected_fields=("value",),
            max_samples=config.max_samples,
        ),),
        plots=(WorkspacePlotDefinition(
            name="Live Soak Telemetry",
            history_seconds=max(config.duration_sec + config.warmup_sec + 1.0, 1.0),
            max_points=config.plot_max_points,
            series=(WorkspacePlotSeries(
                domain_id=config.domain_id,
                topic_name=config.topic_name,
                type_name=config.type_name,
                field_path="value",
                label="value",
            ),),
        ),),
    )


async def run_live_soak(config: LiveSoakConfig) -> LiveSoakReport:
    import rti.connextdds as dds

    prepare_connext_environment()
    dynamic_type = build_telemetry_dynamic_type(dds, config.type_name)
    type_catalog = TypeCatalog()
    type_catalog.register_type(config.type_name, source="in-memory-live-soak", kind="struct")
    client = RtiSubscriptionClient(
        config=RtiSubscriptionConfig(
            poll_interval_sec=config.poll_interval_sec,
            reader_history_depth=config.reader_history_depth,
            reader_resource_max_samples=config.reader_history_depth,
            reader_resource_max_instances=1,
            reader_resource_max_samples_per_instance=config.reader_history_depth,
            reader_take_max_samples=config.reader_take_max_samples,
        ),
        type_registry=InMemoryTelemetryTypeRegistry(config.type_name, dynamic_type),
    )
    session = DataSessionCoordinator(
        build_live_soak_workspace(config),
        client,
        type_catalog=type_catalog,
        config=DataSessionConfig(
            default_max_samples=config.max_samples,
            plot_min_interval_seconds=0.0,
        ),
    )
    runtime = AppRuntime()
    publisher = LiveTelemetryPublisher(dds, config, dynamic_type) if config.start_publisher else None
    errors: List[str] = []
    rss_start = _rss_kb()
    started = time.monotonic()
    published = 0
    polls = 0
    try:
        await session.start()
        if config.warmup_sec > 0.0:
            await asyncio.sleep(config.warmup_sec)
        loop_started = time.monotonic()
        while time.monotonic() - loop_started < config.duration_sec:
            elapsed = time.monotonic() - loop_started
            if publisher is not None:
                target = int(elapsed * config.publish_rate_hz)
                publisher.publish_until(target)
                published = publisher.published
            update = await session.poll_once()
            runtime.record_data_session_update(update)
            polls += 1
            await asyncio.sleep(config.poll_interval_sec)
        update = await session.poll_once()
        runtime.record_data_session_update(update)
        polls += 1
    except Exception as exc:
        errors.append(str(exc))
    finally:
        try:
            await session.close()
        except Exception as exc:
            errors.append(f"close failed: {exc}")
        if publisher is not None:
            try:
                publisher.close()
            except Exception as exc:
                errors.append(f"publisher close failed: {exc}")

    snapshot = session.snapshot()
    metrics = LiveSoakMetrics(
        samples_received=runtime.counters.samples_received,
        samples_dropped=runtime.counters.samples_dropped,
        cached_samples=snapshot.sample_count,
        plot_points=snapshot.plot_point_count,
        published_samples=published,
        poll_count=polls,
        elapsed_sec=time.monotonic() - started,
        rss_start_kb=rss_start,
        rss_end_kb=_rss_kb(),
        errors=tuple(errors),
    )
    return build_report(config, metrics, runtime.counters)


def build_telemetry_dynamic_type(dds: Any, type_name: str) -> Any:
    dynamic_type = dds.StructType(type_name)
    dynamic_type.add_member(dds.Member("source_id", dds.StringType(64)))
    dynamic_type.add_member(dds.Member("index", _uint32_type(dds)))
    dynamic_type.add_member(dds.Member("value", dds.Float64Type()))
    return dynamic_type


def prepare_connext_environment() -> None:
    nddshome = detect_nddshome()
    if nddshome and not os.environ.get("NDDSHOME"):
        os.environ["NDDSHOME"] = nddshome
    ensure_rti_license(nddshome)


def _uint32_type(dds: Any) -> Any:
    uint32 = getattr(dds, "UInt32Type", None) or getattr(dds, "Uint32Type", None)
    if uint32 is None:
        uint32 = getattr(dds, "Int32Type")
    return uint32()


def bounded_dynamic_data_writer_qos(
        dds: Any,
        history_depth: int,
        max_samples: int,
        max_instances: int = 1,
        max_samples_per_instance: int = 0,
) -> Any:
    qos = dds.DataWriterQos()
    depth = max(1, int(history_depth))
    qos.history.kind = _keep_last_history_kind(dds)
    qos.history.depth = depth
    qos.resource_limits.max_samples = max(depth, int(max_samples))
    qos.resource_limits.max_instances = max(1, int(max_instances))
    qos.resource_limits.max_samples_per_instance = max(depth, int(max_samples_per_instance or depth))
    _set_if_present(qos.resource_limits, "initial_samples", min(depth, qos.resource_limits.max_samples))
    _set_if_present(qos.resource_limits, "initial_instances", min(1, qos.resource_limits.max_instances))
    _set_if_present(
        qos.resource_limits,
        "initial_samples_per_instance",
        min(depth, qos.resource_limits.max_samples_per_instance),
    )
    return qos


def _keep_last_history_kind(dds: Any) -> Any:
    for enum_name, value_name in (
            ("HistoryQosPolicyKind", "KEEP_LAST_HISTORY_QOS"),
            ("HistoryKind", "KEEP_LAST"),
            ("HistoryQosPolicyKind", "KEEP_LAST"),
    ):
        enum = getattr(dds, enum_name, None)
        value = getattr(enum, value_name, None)
        if value is not None:
            return value
    raise RuntimeError("Connext Python API does not expose a KEEP_LAST history QoS enum")


def _set_if_present(obj: Any, name: str, value: Any) -> None:
    if hasattr(obj, name):
        setattr(obj, name, value)


def build_report(
        config: LiveSoakConfig,
        metrics: LiveSoakMetrics,
        counters: RuntimeCounters,
) -> LiveSoakReport:
    issues = tuple(evaluate_soak(config, metrics))
    return LiveSoakReport(
        passed=not issues,
        issues=issues,
        config=config,
        metrics=metrics,
        counters=asdict(counters),
    )


def evaluate_soak(config: LiveSoakConfig, metrics: LiveSoakMetrics) -> Tuple[str, ...]:
    issues: List[str] = list(metrics.errors)
    if metrics.samples_received < config.min_samples:
        issues.append(
            f"received {metrics.samples_received} sample(s), expected at least {config.min_samples}"
        )
    if metrics.cached_samples > config.max_samples:
        issues.append(
            f"sample cache exceeded bound: {metrics.cached_samples} > {config.max_samples}"
        )
    if metrics.plot_points > config.plot_max_points:
        issues.append(
            f"plot buffer exceeded bound: {metrics.plot_points} > {config.plot_max_points}"
        )
    if config.memory_growth_limit_mb > 0.0:
        limit_kb = int(config.memory_growth_limit_mb * 1024)
        if metrics.rss_growth_kb > limit_kb:
            issues.append(
                f"RSS growth exceeded bound: {metrics.rss_growth_kb} KiB > {limit_kb} KiB"
            )
    return tuple(issues)


def write_report(report: LiveSoakReport, output_path: str) -> None:
    directory = os.path.dirname(os.path.abspath(output_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as report_file:
        json.dump(report.to_dict(), report_file, indent=2, sort_keys=True)
        report_file.write("\n")


def parse_args(argv: Optional[Iterable[str]] = None) -> LiveSoakConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain-id", type=int, default=LiveSoakConfig.domain_id)
    parser.add_argument("--topic-name", default=LiveSoakConfig.topic_name)
    parser.add_argument("--type-name", default=LiveSoakConfig.type_name)
    parser.add_argument("--duration-sec", type=float, default=LiveSoakConfig.duration_sec)
    parser.add_argument("--warmup-sec", type=float, default=LiveSoakConfig.warmup_sec)
    parser.add_argument("--poll-interval-sec", type=float, default=LiveSoakConfig.poll_interval_sec)
    parser.add_argument("--publish-rate-hz", type=float, default=LiveSoakConfig.publish_rate_hz)
    parser.add_argument("--max-samples", type=int, default=LiveSoakConfig.max_samples)
    parser.add_argument("--plot-max-points", type=int, default=LiveSoakConfig.plot_max_points)
    parser.add_argument("--reader-history-depth", type=int, default=LiveSoakConfig.reader_history_depth)
    parser.add_argument("--reader-take-max-samples", type=int, default=LiveSoakConfig.reader_take_max_samples)
    parser.add_argument("--min-samples", type=int, default=LiveSoakConfig.min_samples)
    parser.add_argument("--memory-growth-limit-mb", type=float, default=LiveSoakConfig.memory_growth_limit_mb)
    parser.add_argument("--no-publisher", action="store_true")
    parser.add_argument("--output", default=LiveSoakConfig.output_path)
    args = parser.parse_args(tuple(argv) if argv is not None else None)
    return LiveSoakConfig(
        domain_id=args.domain_id,
        topic_name=args.topic_name,
        type_name=args.type_name,
        duration_sec=args.duration_sec,
        warmup_sec=args.warmup_sec,
        poll_interval_sec=args.poll_interval_sec,
        publish_rate_hz=args.publish_rate_hz,
        max_samples=args.max_samples,
        plot_max_points=args.plot_max_points,
        reader_history_depth=args.reader_history_depth,
        reader_take_max_samples=args.reader_take_max_samples,
        min_samples=args.min_samples,
        memory_growth_limit_mb=args.memory_growth_limit_mb,
        start_publisher=not args.no_publisher,
        output_path=args.output,
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    config = parse_args(argv)
    report = asyncio.run(run_live_soak(config))
    write_report(report, config.output_path)
    status = "PASS" if report.passed else "FAIL"
    print(
        f"{status}: received={report.metrics.samples_received} "
        f"dropped={report.metrics.samples_dropped} cached={report.metrics.cached_samples} "
        f"plot_points={report.metrics.plot_points} report={config.output_path}"
    )
    for issue in report.issues:
        print(f"ISSUE: {issue}")
    return 0 if report.passed else 1


def _rss_kb() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _safe_close(entity: Any) -> None:
    close = getattr(entity, "close", None)
    if close is not None:
        close()


if __name__ == "__main__":
    sys.exit(main())