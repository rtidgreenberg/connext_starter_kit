"""DDS-free plotting buffers and decimation for rs_gui_v2."""

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, Mapping, Optional, Tuple

from .extractors import FieldExtractionStatus, FieldValueKind, extract_field
from .subscriptions import SampleEnvelope
from .workspace import WorkspacePlotDefinition, WorkspacePlotSeries


@dataclass(frozen=True)
class PlotSamplePoint:
    """One numeric sample value retained for plotting."""

    timestamp: float
    value: float
    source_timestamp: Optional[float] = None
    reception_timestamp: Optional[float] = None
    observed_at: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", float(self.timestamp))
        object.__setattr__(self, "value", float(self.value))
        if self.source_timestamp is not None:
            object.__setattr__(self, "source_timestamp", float(self.source_timestamp))
        if self.reception_timestamp is not None:
            object.__setattr__(self, "reception_timestamp", float(self.reception_timestamp))
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", float(self.observed_at))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "value": self.value,
            "source_timestamp": self.source_timestamp,
            "reception_timestamp": self.reception_timestamp,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlotSamplePoint":
        return cls(
            timestamp=float(data["timestamp"]),
            value=float(data["value"]),
            source_timestamp=data.get("source_timestamp"),
            reception_timestamp=data.get("reception_timestamp"),
            observed_at=data.get("observed_at"),
        )


@dataclass(frozen=True)
class PlotSeriesSnapshot:
    """Immutable UI-facing snapshot for one plot series buffer."""

    series_key: str
    label: str
    domain_id: int
    topic_name: str
    type_name: str
    field_path: str
    points: Tuple[PlotSamplePoint, ...] = field(default_factory=tuple)
    accepted_samples: int = 0
    skipped_samples: int = 0
    dropped_points: int = 0
    decimated_points: int = 0
    last_message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "points", tuple(
            point if isinstance(point, PlotSamplePoint) else PlotSamplePoint.from_dict(point)
            for point in self.points
        ))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_key": self.series_key,
            "label": self.label,
            "domain_id": self.domain_id,
            "topic_name": self.topic_name,
            "type_name": self.type_name,
            "field_path": self.field_path,
            "points": [point.to_dict() for point in self.points],
            "accepted_samples": self.accepted_samples,
            "skipped_samples": self.skipped_samples,
            "dropped_points": self.dropped_points,
            "decimated_points": self.decimated_points,
            "last_message": self.last_message,
        }


@dataclass(frozen=True)
class PlotBufferSnapshot:
    """Immutable UI-facing snapshot for a plot definition."""

    name: str
    series: Tuple[PlotSeriesSnapshot, ...] = field(default_factory=tuple)
    history_seconds: float = 60.0
    max_points: int = 2000

    def __post_init__(self) -> None:
        object.__setattr__(self, "history_seconds", float(self.history_seconds))
        object.__setattr__(self, "max_points", int(self.max_points))
        object.__setattr__(self, "series", tuple(self.series))

    @property
    def point_count(self) -> int:
        return sum(len(series.points) for series in self.series)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "series": [series.to_dict() for series in self.series],
            "history_seconds": self.history_seconds,
            "max_points": self.max_points,
        }


@dataclass(frozen=True)
class PlotUpdateResult:
    """Result of applying one sample to one series buffer."""

    series_key: str
    accepted: bool = False
    skipped: bool = False
    decimated: bool = False
    dropped_points: int = 0
    message: str = ""


class PlotSeriesBuffer:
    """Bounded numeric buffer for one persisted plot series selection."""

    def __init__(
            self,
            series: WorkspacePlotSeries,
            history_seconds: float = 60.0,
            max_points: int = 2000,
            min_interval_seconds: float = 0.0,
    ) -> None:
        self.series = series
        self.history_seconds = max(0.1, float(history_seconds))
        self.max_points = max(1, int(max_points))
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._points: Deque[PlotSamplePoint] = deque()
        self.accepted_samples = 0
        self.skipped_samples = 0
        self.dropped_points = 0
        self.decimated_points = 0
        self.last_message = ""

    @property
    def series_key(self) -> str:
        return self.series.key

    def update_from_sample(self, sample: SampleEnvelope) -> PlotUpdateResult:
        if not self.series.enabled:
            return self._skip("series disabled")
        if not sample.valid:
            return self._skip("sample is invalid")
        if not self._matches_sample(sample):
            return self._skip("sample does not match series")

        extraction = extract_field(sample.data, self.series.field_path)
        if extraction.status != FieldExtractionStatus.FOUND:
            return self._skip(extraction.message or extraction.status.value)
        if extraction.kind != FieldValueKind.NUMERIC:
            return self._skip(f"field is not numeric: {self.series.field_path}")

        point = PlotSamplePoint(
            timestamp=_sample_timestamp(sample),
            value=extraction.value,
            source_timestamp=sample.info.source_timestamp,
            reception_timestamp=sample.info.reception_timestamp,
            observed_at=sample.observed_at,
        )
        return self.append(point)

    def append(self, point: PlotSamplePoint) -> PlotUpdateResult:
        point = point if isinstance(point, PlotSamplePoint) else PlotSamplePoint.from_dict(point)
        decimated = False
        if self._points and self.min_interval_seconds > 0.0:
            previous = self._points[-1]
            if point.timestamp - previous.timestamp < self.min_interval_seconds:
                self._points[-1] = point
                self.decimated_points += 1
                decimated = True
            else:
                self._points.append(point)
        else:
            self._points.append(point)

        self.accepted_samples += 1
        dropped = self._prune(point.timestamp)
        self.last_message = "decimated" if decimated else "accepted"
        return PlotUpdateResult(
            series_key=self.series_key,
            accepted=True,
            decimated=decimated,
            dropped_points=dropped,
            message=self.last_message,
        )

    def snapshot(self) -> PlotSeriesSnapshot:
        return PlotSeriesSnapshot(
            series_key=self.series_key,
            label=self.series.label or self.series.field_path,
            domain_id=self.series.domain_id,
            topic_name=self.series.topic_name,
            type_name=self.series.type_name,
            field_path=self.series.field_path,
            points=tuple(self._points),
            accepted_samples=self.accepted_samples,
            skipped_samples=self.skipped_samples,
            dropped_points=self.dropped_points,
            decimated_points=self.decimated_points,
            last_message=self.last_message,
        )

    def _matches_sample(self, sample: SampleEnvelope) -> bool:
        if sample.domain_id != self.series.domain_id:
            return False
        if sample.topic_name != self.series.topic_name:
            return False
        if self.series.type_name and sample.type_name != self.series.type_name:
            return False
        return True

    def _skip(self, message: str) -> PlotUpdateResult:
        self.skipped_samples += 1
        self.last_message = message
        return PlotUpdateResult(series_key=self.series_key, skipped=True, message=message)

    def _prune(self, current_timestamp: float) -> int:
        dropped = 0
        cutoff = current_timestamp - self.history_seconds
        while self._points and self._points[0].timestamp < cutoff:
            self._points.popleft()
            dropped += 1
        while len(self._points) > self.max_points:
            self._points.popleft()
            dropped += 1
        self.dropped_points += dropped
        return dropped


class PlotBufferSet:
    """Collection of series buffers for one workspace plot definition."""

    def __init__(
            self,
            plot: WorkspacePlotDefinition,
            min_interval_seconds: float = 0.0,
    ) -> None:
        self.plot = plot
        self._buffers: Dict[str, PlotSeriesBuffer] = {
            series.key: PlotSeriesBuffer(
                series,
                history_seconds=plot.history_seconds,
                max_points=plot.max_points,
                min_interval_seconds=min_interval_seconds,
            )
            for series in plot.series
        }

    def update_from_sample(self, sample: SampleEnvelope) -> Tuple[PlotUpdateResult, ...]:
        if not self.plot.enabled:
            return ()
        return tuple(
            buffer.update_from_sample(sample)
            for buffer in self._buffers.values()
            if buffer._matches_sample(sample)
        )

    def snapshot(self) -> PlotBufferSnapshot:
        return PlotBufferSnapshot(
            name=self.plot.name,
            series=tuple(buffer.snapshot() for buffer in self._buffers.values()),
            history_seconds=self.plot.history_seconds,
            max_points=self.plot.max_points,
        )

    def buffer_for(self, series_key: str) -> Optional[PlotSeriesBuffer]:
        return self._buffers.get(str(series_key))


def build_plot_buffer_sets(
        plots: Iterable[WorkspacePlotDefinition],
        min_interval_seconds: float = 0.0,
) -> Tuple[PlotBufferSet, ...]:
    """Create plot buffers from persisted workspace plot definitions."""
    return tuple(
        PlotBufferSet(plot, min_interval_seconds=min_interval_seconds)
        for plot in plots
        if plot.enabled
    )


def _sample_timestamp(sample: SampleEnvelope) -> float:
    if sample.info.source_timestamp is not None:
        return float(sample.info.source_timestamp)
    if sample.info.reception_timestamp is not None:
        return float(sample.info.reception_timestamp)
    return float(sample.observed_at)