"""Plot view for numeric field time-series visualization.

Uses Dear PyGui for live line-series rendering.
"""

import asyncio
import time
from collections import deque
from typing import Optional

from ..fields import get_field_value


def plot_series_from_points(points):
    """Convert plot points into Dear PyGui line-series arrays."""
    point_list = list(points)
    if not point_list:
        return [], []
    start_time = point_list[0].timestamp
    return (
        [point.timestamp - start_time for point in point_list],
        [point.value for point in point_list],
    )


async def run_plot(reader, field_path: str, topic_name: str, history_seconds: int = 30):
    """Run a live plot of a numeric field over time.

    Render with Dear PyGui.
    """
    await _run_dearpygui_plot(reader, field_path, topic_name, history_seconds)


async def _run_dearpygui_plot(reader, field_path: str, topic_name: str, history_seconds: int):
    """Render a live DearPyGui line plot."""
    import dearpygui.dearpygui as dpg
    from ..debug_log import debug

    max_points = history_seconds * 20  # ~20Hz assumption
    timestamps = deque(maxlen=max_points)
    values = deque(maxlen=max_points)

    dpg.create_context()
    dpg.create_viewport(title=f"rti_view — {topic_name}.{field_path}", width=900, height=500)

    with dpg.window(label="Plot", no_close=True, no_collapse=True, tag="plot_primary"):
        with dpg.plot(label=f"{topic_name}.{field_path}", height=-1, width=-1):
            x_axis = dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)")
            y_axis = dpg.add_plot_axis(dpg.mvYAxis, label=field_path)
            series = dpg.add_line_series([], [], parent=y_axis, label=field_path)

    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("plot_primary", True)

    start_time = time.time()
    debug("plot_view", f"started: topic={topic_name} field={field_path} history={history_seconds}s")

    while dpg.is_dearpygui_running():
        accepted = 0
        for data, info in reader.take():
            if info.valid:
                value = get_field_value(data, field_path)
                if value is not None:
                    now = time.time() - start_time
                    timestamps.append(now)
                    values.append(float(value))
                    accepted += 1

        if accepted:
            debug("plot_view", f"accepted={accepted} total_points={len(timestamps)} last_value={values[-1]:.3f}")
            dpg.set_value(series, [list(timestamps), list(values)])
            dpg.fit_axis_data(x_axis)
            dpg.fit_axis_data(y_axis)

        dpg.render_dearpygui_frame()
        await asyncio.sleep(0.016)  # ~60fps

    dpg.destroy_context()
