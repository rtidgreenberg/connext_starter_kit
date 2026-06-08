#!/usr/bin/env python3
"""Live DDS discovery churn gate for rs_gui_v2 topic discovery."""

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
import os
import sys
import time
from typing import Any, Iterable, List, Mapping, Optional, Tuple
from uuid import uuid4


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(APP_DIR, "..", ".."))
VENV_PYTHON = os.path.join(REPO_ROOT, "connext_dds_env", "bin", "python")
DEFAULT_OUTPUT = os.path.join(APP_DIR, "live_reports", "discovery_churn_report.json")


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
from app_core.rti_discovery import RtiTopicDiscoveryClient, RtiTopicDiscoveryConfig  # noqa: E402


@dataclass(frozen=True)
class DiscoveryChurnConfig:
    """CLI-configurable parameters for the live discovery churn gate."""

    domain_id: int = 65
    iterations: int = 10
    namespace: str = "RsGuiV2DiscoveryChurn"
    type_name: str = "RsGuiV2DiscoveryChurnType"
    observe_timeout_sec: float = 5.0
    settle_timeout_sec: float = 5.0
    poll_interval_sec: float = 0.1
    stale_endpoint_sec: float = 2.0
    min_observed_ratio: float = 1.0
    output_path: str = DEFAULT_OUTPUT

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "iterations", max(1, int(self.iterations)))
        object.__setattr__(self, "namespace", str(self.namespace).strip("/") or "RsGuiV2DiscoveryChurn")
        object.__setattr__(self, "type_name", str(self.type_name) or "RsGuiV2DiscoveryChurnType")
        object.__setattr__(self, "observe_timeout_sec", max(0.1, float(self.observe_timeout_sec)))
        object.__setattr__(self, "settle_timeout_sec", max(0.1, float(self.settle_timeout_sec)))
        object.__setattr__(self, "poll_interval_sec", max(0.01, float(self.poll_interval_sec)))
        object.__setattr__(self, "stale_endpoint_sec", max(0.0, float(self.stale_endpoint_sec)))
        object.__setattr__(self, "min_observed_ratio", min(1.0, max(0.0, float(self.min_observed_ratio))))


@dataclass(frozen=True)
class DiscoveryChurnIteration:
    """Measured discovery result for one created topic."""

    index: int
    topic_name: str
    observed: bool
    writer_count: int = 0
    reader_count: int = 0
    observe_elapsed_sec: float = 0.0
    issues: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DiscoveryChurnMetrics:
    """Aggregate live discovery churn metrics."""

    expected_topics: int = 0
    observed_topics: int = 0
    final_live_topics: int = 0
    final_live_topic_names: Tuple[str, ...] = field(default_factory=tuple)
    elapsed_sec: float = 0.0
    errors: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def observed_ratio(self) -> float:
        if self.expected_topics <= 0:
            return 0.0
        return float(self.observed_topics) / float(self.expected_topics)


@dataclass(frozen=True)
class DiscoveryChurnReport:
    """Serializable pass/fail report for discovery churn."""

    passed: bool
    issues: Tuple[str, ...]
    config: DiscoveryChurnConfig
    metrics: DiscoveryChurnMetrics
    iterations: Tuple[DiscoveryChurnIteration, ...]
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Mapping[str, Any]:
        metrics = asdict(self.metrics)
        metrics["observed_ratio"] = self.metrics.observed_ratio
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "config": asdict(self.config),
            "metrics": metrics,
            "iterations": [asdict(iteration) for iteration in self.iterations],
            "generated_at": self.generated_at,
        }


class DiscoveryChurnEndpoints:
    """Owns live DDS entities created for one churn iteration."""

    def __init__(self, dds: Any, participant: Any, topic_name: str, dynamic_type: Any) -> None:
        self._dds = dds
        self._participant = participant
        self._topic = dds.DynamicData.Topic(participant, topic_name, dynamic_type)
        self._reader = dds.DynamicData.DataReader(participant.implicit_subscriber, self._topic)
        self._writer = dds.DynamicData.DataWriter(participant.implicit_publisher, self._topic)
        self._published = False

    def publish_once(self, index: int) -> None:
        if self._published:
            return
        sample = self._writer.create_data()
        sample["index"] = int(index)
        sample["value"] = float(index)
        self._writer.write(sample)
        self._published = True

    def close(self) -> None:
        for entity in (self._writer, self._reader, self._topic):
            _safe_close(entity)


async def run_discovery_churn(config: DiscoveryChurnConfig) -> DiscoveryChurnReport:
    import rti.connextdds as dds

    prepare_connext_environment()
    run_id = uuid4().hex[:8]
    topic_prefix = f"{config.namespace}/{run_id}"
    discovery = RtiTopicDiscoveryClient(config=RtiTopicDiscoveryConfig(
        poll_interval_sec=config.poll_interval_sec,
        endpoint_stale_after_sec=config.stale_endpoint_sec,
    ))
    participant = dds.DomainParticipant(config.domain_id)
    dynamic_type = build_churn_dynamic_type(dds, config.type_name)
    iterations: List[DiscoveryChurnIteration] = []
    errors: List[str] = []
    started = time.monotonic()
    try:
        await discovery.scan(config.domain_id, include_internal=True)
        for index in range(config.iterations):
            topic_name = f"{topic_prefix}/{index}"
            endpoints: Optional[DiscoveryChurnEndpoints] = None
            issues: List[str] = []
            observed = False
            writer_count = 0
            reader_count = 0
            observe_started = time.monotonic()
            try:
                endpoints = DiscoveryChurnEndpoints(dds, participant, topic_name, dynamic_type)
                endpoints.publish_once(index)
                observed_topic = await wait_for_topic(
                    discovery,
                    config.domain_id,
                    topic_name,
                    timeout_sec=config.observe_timeout_sec,
                    poll_interval_sec=config.poll_interval_sec,
                )
                if observed_topic is None:
                    issues.append(f"topic {topic_name} was not discovered")
                else:
                    observed = True
                    writer_count = observed_topic.writer_count
                    reader_count = observed_topic.reader_count
            except Exception as exc:
                issues.append(str(exc))
            finally:
                if endpoints is not None:
                    try:
                        endpoints.close()
                    except Exception as exc:
                        issues.append(f"endpoint close failed: {exc}")
            iterations.append(DiscoveryChurnIteration(
                index=index,
                topic_name=topic_name,
                observed=observed,
                writer_count=writer_count,
                reader_count=reader_count,
                observe_elapsed_sec=time.monotonic() - observe_started,
                issues=tuple(issues),
            ))
    except Exception as exc:
        errors.append(str(exc))
    finally:
        try:
            close_contained = getattr(participant, "close_contained_entities", None)
            if close_contained is not None:
                close_contained()
        except Exception as exc:
            errors.append(f"participant contained-entity close failed: {exc}")
        finally:
            try:
                _safe_close(participant)
            except Exception as exc:
                errors.append(f"participant close failed: {exc}")

    final_live = await wait_for_namespace_empty(
        discovery,
        config.domain_id,
        topic_prefix,
        timeout_sec=config.settle_timeout_sec,
        poll_interval_sec=config.poll_interval_sec,
    )
    try:
        await discovery.close()
    except Exception as exc:
        errors.append(f"discovery close failed: {exc}")

    metrics = DiscoveryChurnMetrics(
        expected_topics=config.iterations,
        observed_topics=sum(1 for iteration in iterations if iteration.observed),
        final_live_topics=len(final_live),
        final_live_topic_names=tuple(topic.topic_name for topic in final_live),
        elapsed_sec=time.monotonic() - started,
        errors=tuple(errors),
    )
    return build_report(config, metrics, tuple(iterations))


async def wait_for_topic(
        discovery: RtiTopicDiscoveryClient,
        domain_id: int,
        topic_name: str,
        timeout_sec: float,
        poll_interval_sec: float,
):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() <= deadline:
        topics = await discovery.scan(domain_id, include_internal=True)
        for topic in topics:
            if topic.topic_name == topic_name and topic.writer_count > 0 and topic.reader_count > 0:
                return topic
        await asyncio.sleep(poll_interval_sec)
    return None


async def wait_for_namespace_empty(
        discovery: RtiTopicDiscoveryClient,
        domain_id: int,
        topic_prefix: str,
        timeout_sec: float,
        poll_interval_sec: float,
):
    deadline = time.monotonic() + timeout_sec
    latest = tuple()
    while time.monotonic() <= deadline:
        latest = live_topics_in_namespace(await discovery.scan(domain_id, include_internal=True), topic_prefix)
        if not latest:
            return tuple()
        await asyncio.sleep(poll_interval_sec)
    return latest


def live_topics_in_namespace(topics: Iterable[Any], topic_prefix: str) -> Tuple[Any, ...]:
    prefix = f"{topic_prefix.rstrip('/')}/"
    return tuple(
        topic for topic in topics
        if str(getattr(topic, "topic_name", "")).startswith(prefix)
        and int(getattr(topic, "endpoint_count", 0)) > 0
    )


def build_churn_dynamic_type(dds: Any, type_name: str) -> Any:
    dynamic_type = dds.StructType(type_name)
    dynamic_type.add_member(dds.Member("index", _uint32_type(dds)))
    dynamic_type.add_member(dds.Member("value", dds.Float64Type()))
    return dynamic_type


def prepare_connext_environment() -> None:
    nddshome = detect_nddshome()
    if nddshome and not os.environ.get("NDDSHOME"):
        os.environ["NDDSHOME"] = nddshome
    ensure_rti_license(nddshome)


def build_report(
        config: DiscoveryChurnConfig,
        metrics: DiscoveryChurnMetrics,
        iterations: Tuple[DiscoveryChurnIteration, ...],
) -> DiscoveryChurnReport:
    issues = tuple(evaluate_churn(config, metrics, iterations))
    return DiscoveryChurnReport(
        passed=not issues,
        issues=issues,
        config=config,
        metrics=metrics,
        iterations=iterations,
    )


def evaluate_churn(
        config: DiscoveryChurnConfig,
        metrics: DiscoveryChurnMetrics,
        iterations: Tuple[DiscoveryChurnIteration, ...],
) -> Tuple[str, ...]:
    issues: List[str] = list(metrics.errors)
    for iteration in iterations:
        issues.extend(iteration.issues)
    if metrics.observed_ratio < config.min_observed_ratio:
        issues.append(
            f"observed {metrics.observed_topics}/{metrics.expected_topics} topics "
            f"({metrics.observed_ratio:.2%}), expected at least {config.min_observed_ratio:.2%}"
        )
    if metrics.final_live_topics:
        issues.append(
            "discovery namespace still has live topics after settle: "
            + ", ".join(metrics.final_live_topic_names)
        )
    return tuple(issues)


def write_report(report: DiscoveryChurnReport, output_path: str) -> None:
    directory = os.path.dirname(os.path.abspath(output_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as report_file:
        json.dump(report.to_dict(), report_file, indent=2, sort_keys=True)
        report_file.write("\n")


def parse_args(argv: Optional[Iterable[str]] = None) -> DiscoveryChurnConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain-id", type=int, default=DiscoveryChurnConfig.domain_id)
    parser.add_argument("--iterations", type=int, default=DiscoveryChurnConfig.iterations)
    parser.add_argument("--namespace", default=DiscoveryChurnConfig.namespace)
    parser.add_argument("--type-name", default=DiscoveryChurnConfig.type_name)
    parser.add_argument("--observe-timeout-sec", type=float, default=DiscoveryChurnConfig.observe_timeout_sec)
    parser.add_argument("--settle-timeout-sec", type=float, default=DiscoveryChurnConfig.settle_timeout_sec)
    parser.add_argument("--poll-interval-sec", type=float, default=DiscoveryChurnConfig.poll_interval_sec)
    parser.add_argument("--stale-endpoint-sec", type=float, default=DiscoveryChurnConfig.stale_endpoint_sec)
    parser.add_argument("--min-observed-ratio", type=float, default=DiscoveryChurnConfig.min_observed_ratio)
    parser.add_argument("--output", default=DiscoveryChurnConfig.output_path)
    args = parser.parse_args(tuple(argv) if argv is not None else None)
    return DiscoveryChurnConfig(
        domain_id=args.domain_id,
        iterations=args.iterations,
        namespace=args.namespace,
        type_name=args.type_name,
        observe_timeout_sec=args.observe_timeout_sec,
        settle_timeout_sec=args.settle_timeout_sec,
        poll_interval_sec=args.poll_interval_sec,
        stale_endpoint_sec=args.stale_endpoint_sec,
        min_observed_ratio=args.min_observed_ratio,
        output_path=args.output,
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    config = parse_args(argv)
    report = asyncio.run(run_discovery_churn(config))
    write_report(report, config.output_path)
    status = "PASS" if report.passed else "FAIL"
    print(
        f"{status}: observed={report.metrics.observed_topics}/{report.metrics.expected_topics} "
        f"final_live={report.metrics.final_live_topics} report={config.output_path}"
    )
    for issue in report.issues:
        print(f"ISSUE: {issue}")
    return 0 if report.passed else 1


def _uint32_type(dds: Any) -> Any:
    uint32 = getattr(dds, "UInt32Type", None) or getattr(dds, "Uint32Type", None)
    if uint32 is None:
        uint32 = getattr(dds, "Int32Type")
    return uint32()


def _safe_close(entity: Any) -> None:
    close = getattr(entity, "close", None)
    if close is not None:
        close()


if __name__ == "__main__":
    sys.exit(main())
