"""Plots tab controller wiring data-session plot snapshots into GUI views."""

from dataclasses import dataclass, replace
import time
from typing import Any, Callable, Mapping, Optional, Tuple

from app_core import (
    DataSessionSnapshot,
    PlotBufferSnapshot,
    PlotSeriesSnapshot,
    WorkspacePlotDefinition,
    WorkspacePlotSeries,
)

from .plots_tab import PlotsTabViewModel, build_plots_tab_view_model


@dataclass(frozen=True)
class PlotsTabControllerConfig:
    """Runtime wiring options for the Plots tab controller."""

    selected_plot_name: str = ""
    paused: bool = False
    max_point_rows: int = 24

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_plot_name", str(self.selected_plot_name))
        object.__setattr__(self, "paused", bool(self.paused))
        object.__setattr__(self, "max_point_rows", max(1, int(self.max_point_rows)))


class PlotsTabController:
    """Build Plots tab snapshots from app-core plot buffer snapshots."""

    def __init__(
            self,
            plot_snapshots: Tuple[PlotBufferSnapshot, ...] = (),
            data_session_snapshot_provider: Optional[Callable[[], Optional[DataSessionSnapshot]]] = None,
            config: Optional[PlotsTabControllerConfig] = None,
            clock=time.time,
    ) -> None:
        self._plot_snapshots = tuple(plot_snapshots)
        self._data_session_snapshot_provider = data_session_snapshot_provider
        self._config = config or PlotsTabControllerConfig()
        self._clock = clock
        self._last_view = PlotsTabViewModel(selected_plot_name=self._config.selected_plot_name)

    @property
    def selected_plot_name(self) -> str:
        return self._config.selected_plot_name

    @property
    def paused(self) -> bool:
        return self._config.paused

    @property
    def last_view(self) -> PlotsTabViewModel:
        return self._last_view

    def select_plot(self, name: str) -> None:
        self._config = replace(self._config, selected_plot_name=str(name))

    def set_paused(self, paused: bool) -> None:
        self._config = replace(self._config, paused=bool(paused))

    def set_plot_snapshots(self, snapshots: Tuple[PlotBufferSnapshot, ...]) -> None:
        self._plot_snapshots = tuple(snapshots)

    def apply_data_session_snapshot(self, snapshot: DataSessionSnapshot) -> None:
        """Use a data-session snapshot as the source for plot buffer state."""

        self._plot_snapshots = plots_inputs_from_data_session_snapshot(snapshot)

    def workspace_plot_definitions(self) -> Tuple[WorkspacePlotDefinition, ...]:
        """Return persistable plot layout definitions without retained samples."""

        return tuple(_plot_definition_from_snapshot(snapshot) for snapshot in self._plot_snapshots)

    def workspace_metadata(self) -> Mapping[str, Any]:
        """Return GUI-only Plots preferences for workspace metadata."""

        return {
            "selected_plot_name": self._config.selected_plot_name,
            "paused": self._config.paused,
        }

    def apply_workspace_intent(
            self,
            plots: Tuple[WorkspacePlotDefinition, ...] = (),
            metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Restore declarative Plots state from a workspace document."""

        metadata = dict(metadata or {})
        self._plot_snapshots = tuple(_plot_snapshot_from_definition(plot) for plot in plots)
        self._config = replace(
            self._config,
            selected_plot_name=str(metadata.get("selected_plot_name", "")),
            paused=bool(metadata.get("paused", False)),
        )

    async def refresh_view(self) -> PlotsTabViewModel:
        """Return the next Plots-tab view from the current plot snapshots."""

        diagnostics = []
        if self._data_session_snapshot_provider is not None:
            try:
                snapshot = self._data_session_snapshot_provider()
                if snapshot is not None:
                    self.apply_data_session_snapshot(snapshot)
            except Exception as exc:
                diagnostics.append(f"Data session snapshot failed: {exc}")

        view = build_plots_tab_view_model(
            plots=self._plot_snapshots,
            selected_plot_name=self._config.selected_plot_name,
            paused=self._config.paused,
            diagnostics=diagnostics,
            now=self._clock(),
            max_point_rows=self._config.max_point_rows,
        )
        if view.selected_plot_name and view.selected_plot_name != self._config.selected_plot_name:
            self._config = replace(self._config, selected_plot_name=view.selected_plot_name)
        self._last_view = view
        return view


def plots_inputs_from_data_session_snapshot(
        snapshot: DataSessionSnapshot,
) -> Tuple[PlotBufferSnapshot, ...]:
    """Extract Plots-tab plot buffer inputs from a data-session snapshot."""

    return tuple(snapshot.plots)


def _plot_definition_from_snapshot(snapshot: PlotBufferSnapshot) -> WorkspacePlotDefinition:
    return WorkspacePlotDefinition(
        name=snapshot.name,
        history_seconds=snapshot.history_seconds,
        max_points=snapshot.max_points,
        series=tuple(
            WorkspacePlotSeries(
                domain_id=series.domain_id,
                topic_name=series.topic_name,
                type_name=series.type_name,
                field_path=series.field_path,
                label=series.label,
            )
            for series in snapshot.series
        ),
    )


def _plot_snapshot_from_definition(plot: WorkspacePlotDefinition) -> PlotBufferSnapshot:
    return PlotBufferSnapshot(
        name=plot.name,
        history_seconds=plot.history_seconds,
        max_points=plot.max_points,
        series=tuple(
            PlotSeriesSnapshot(
                series_key=series.key,
                label=series.label or series.field_path,
                domain_id=series.domain_id,
                topic_name=series.topic_name,
                type_name=series.type_name,
                field_path=series.field_path,
            )
            for series in plot.series
        ),
    )