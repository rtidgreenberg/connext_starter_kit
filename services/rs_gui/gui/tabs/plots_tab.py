"""Plots tab view models for bounded numeric series snapshots."""

from dataclasses import dataclass, field
import time
from typing import Iterable, Mapping, Optional, Tuple

from app_core import PlotBufferSnapshot, PlotSamplePoint, PlotSeriesSnapshot


@dataclass(frozen=True)
class PlotActionView:
    """One Plots-tab command affordance."""

    action_id: str
    label: str
    enabled: bool
    reason: str = ""


@dataclass(frozen=True)
class PlotRow:
    """One configured plot row."""

    name: str
    series_count: int
    point_count: int
    history_seconds: float
    max_points: int
    selected: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "series_count", int(self.series_count))
        object.__setattr__(self, "point_count", int(self.point_count))
        object.__setattr__(self, "history_seconds", float(self.history_seconds))
        object.__setattr__(self, "max_points", int(self.max_points))
        object.__setattr__(self, "selected", bool(self.selected))
        object.__setattr__(self, "enabled", bool(self.enabled))


@dataclass(frozen=True)
class PlotSeriesRow:
    """One plot series summary shown for the selected plot."""

    series_key: str
    label: str
    domain_id: int
    topic_name: str
    type_name: str
    field_path: str
    point_count: int
    latest_value: str = ""
    latest_timestamp: str = ""
    accepted_samples: int = 0
    skipped_samples: int = 0
    dropped_points: int = 0
    decimated_points: int = 0
    status: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "point_count", int(self.point_count))
        object.__setattr__(self, "accepted_samples", int(self.accepted_samples))
        object.__setattr__(self, "skipped_samples", int(self.skipped_samples))
        object.__setattr__(self, "dropped_points", int(self.dropped_points))
        object.__setattr__(self, "decimated_points", int(self.decimated_points))


@dataclass(frozen=True)
class PlotPointRow:
    """One retained plot point row for deterministic headless rendering."""

    series_key: str
    label: str
    timestamp: str
    value: str
    source: str = ""


@dataclass(frozen=True)
class PlotsTabViewModel:
    """Immutable Plots-tab snapshot consumed by the GUI renderer."""

    selected_plot_name: str = ""
    paused: bool = False
    rows: Tuple[PlotRow, ...] = field(default_factory=tuple)
    series: Tuple[PlotSeriesRow, ...] = field(default_factory=tuple)
    point_rows: Tuple[PlotPointRow, ...] = field(default_factory=tuple)
    actions: Tuple[PlotActionView, ...] = field(default_factory=tuple)
    diagnostics: Tuple[str, ...] = field(default_factory=tuple)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "paused", bool(self.paused))
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "series", tuple(self.series))
        object.__setattr__(self, "point_rows", tuple(self.point_rows))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "diagnostics", tuple(str(item) for item in self.diagnostics))
        object.__setattr__(self, "updated_at", float(self.updated_at))

    @property
    def selected_plot(self) -> Optional[PlotRow]:
        for row in self.rows:
            if row.name == self.selected_plot_name:
                return row
        return None

    @property
    def visible_plot_count(self) -> int:
        return len(self.rows)

    @property
    def total_point_count(self) -> int:
        return sum(row.point_count for row in self.rows)

    @property
    def action_by_id(self) -> Mapping[str, PlotActionView]:
        return {action.action_id: action for action in self.actions}


def build_plots_tab_view_model(
        plots: Iterable[PlotBufferSnapshot] = (),
        selected_plot_name: str = "",
        paused: bool = False,
        diagnostics: Iterable[str] = (),
        now: float = None,
        max_point_rows: int = 24,
) -> PlotsTabViewModel:
    """Build a Plots-tab snapshot from app-core plot buffer snapshots."""

    plots = tuple(sorted(plots, key=lambda plot: plot.name.lower()))
    now = time.time() if now is None else float(now)
    max_point_rows = max(1, int(max_point_rows))
    selected_plot_name = _selected_plot_name(plots, selected_plot_name)
    selected_plot = next((plot for plot in plots if plot.name == selected_plot_name), None)
    rows = tuple(_plot_row(plot, selected_plot_name) for plot in plots)
    series = tuple(_series_row(item) for item in selected_plot.series) if selected_plot else ()
    point_rows = _point_rows(selected_plot, max_point_rows=max_point_rows) if selected_plot else ()
    return PlotsTabViewModel(
        selected_plot_name=selected_plot_name,
        paused=paused,
        rows=rows,
        series=series,
        point_rows=point_rows,
        actions=_plot_actions(selected_plot, paused),
        diagnostics=tuple(str(item) for item in diagnostics) + _diagnostics(plots, selected_plot),
        updated_at=now,
    )


def build_mock_plots_tab_view_model(now: float = 120.0) -> PlotsTabViewModel:
    """Return a deterministic Plots-tab snapshot for GUI smoke rendering."""

    return build_plots_tab_view_model(
        plots=_mock_plot_snapshots(now),
        selected_plot_name="Robot Motion",
        now=now,
    )


def _selected_plot_name(plots: Tuple[PlotBufferSnapshot, ...], requested: str) -> str:
    if requested and any(plot.name == requested for plot in plots):
        return str(requested)
    if plots:
        return plots[0].name
    return str(requested)


def _plot_row(plot: PlotBufferSnapshot, selected_plot_name: str) -> PlotRow:
    return PlotRow(
        name=plot.name,
        series_count=len(plot.series),
        point_count=plot.point_count,
        history_seconds=plot.history_seconds,
        max_points=plot.max_points,
        selected=plot.name == selected_plot_name,
    )


def _series_row(series: PlotSeriesSnapshot) -> PlotSeriesRow:
    latest = series.points[-1] if series.points else None
    return PlotSeriesRow(
        series_key=series.series_key,
        label=series.label,
        domain_id=series.domain_id,
        topic_name=series.topic_name,
        type_name=series.type_name,
        field_path=series.field_path,
        point_count=len(series.points),
        latest_value=_number_text(latest.value) if latest is not None else "",
        latest_timestamp=_timestamp_text(latest.timestamp) if latest is not None else "",
        accepted_samples=series.accepted_samples,
        skipped_samples=series.skipped_samples,
        dropped_points=series.dropped_points,
        decimated_points=series.decimated_points,
        status=series.last_message or ("receiving" if series.points else "waiting"),
    )


def _point_rows(plot: PlotBufferSnapshot, max_point_rows: int) -> Tuple[PlotPointRow, ...]:
    rows = []
    for series in plot.series:
        for point in series.points[-max_point_rows:]:
            rows.append(_point_row(series, point))
    rows.sort(key=lambda row: (float(row.timestamp), row.label), reverse=True)
    return tuple(rows[:max_point_rows])


def _point_row(series: PlotSeriesSnapshot, point: PlotSamplePoint) -> PlotPointRow:
    return PlotPointRow(
        series_key=series.series_key,
        label=series.label,
        timestamp=_timestamp_text(point.timestamp),
        value=_number_text(point.value),
        source=_timestamp_source(point),
    )


def _plot_actions(
        selected_plot: Optional[PlotBufferSnapshot],
        paused: bool,
) -> Tuple[PlotActionView, ...]:
    has_plot = selected_plot is not None
    return (
        PlotActionView("pause" if not paused else "resume", "Resume" if paused else "Pause", has_plot),
        PlotActionView("clear", "Clear", has_plot, "no plot selected" if not has_plot else ""),
        PlotActionView("save_layout", "Save Layout", has_plot, "no plot selected" if not has_plot else ""),
    )


def _diagnostics(
        plots: Tuple[PlotBufferSnapshot, ...],
        selected_plot: Optional[PlotBufferSnapshot],
) -> Tuple[str, ...]:
    if not plots:
        return ("No plot buffers are configured",)
    if selected_plot is None:
        return ("Selected plot is not available",)
    if not selected_plot.series:
        return (f"Plot has no series: {selected_plot.name}",)
    if selected_plot.point_count == 0:
        return (f"Plot has no retained points: {selected_plot.name}",)
    return ()


def _timestamp_source(point: PlotSamplePoint) -> str:
    if point.source_timestamp is not None:
        return "source"
    if point.reception_timestamp is not None:
        return "reception"
    if point.observed_at is not None:
        return "observed"
    return "buffer"


def _timestamp_text(value: float) -> str:
    return f"{float(value):.3f}"


def _number_text(value: float) -> str:
    return f"{float(value):.6g}"


def _mock_plot_snapshots(now: float) -> Tuple[PlotBufferSnapshot, ...]:
    velocity_points = tuple(
        PlotSamplePoint(timestamp=now - offset, value=value, source_timestamp=now - offset)
        for offset, value in ((6.0, 1.2), (4.0, 1.35), (2.0, 1.7), (0.0, 1.55))
    )
    x_points = tuple(
        PlotSamplePoint(timestamp=now - offset, value=value, source_timestamp=now - offset)
        for offset, value in ((6.0, 10.8), (4.0, 11.4), (2.0, 12.5), (0.0, 13.1))
    )
    return (PlotBufferSnapshot(
        name="Robot Motion",
        history_seconds=30.0,
        max_points=512,
        series=(
            PlotSeriesSnapshot(
                series_key="0:RobotTelemetry:velocity",
                label="Velocity",
                domain_id=0,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                field_path="velocity",
                points=velocity_points,
                accepted_samples=42,
                skipped_samples=0,
                decimated_points=3,
                last_message="accepted",
            ),
            PlotSeriesSnapshot(
                series_key="0:RobotTelemetry:pose.x",
                label="Pose X",
                domain_id=0,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                field_path="pose.x",
                points=x_points,
                accepted_samples=42,
                skipped_samples=1,
                decimated_points=3,
                last_message="accepted",
            ),
        ),
    ),)