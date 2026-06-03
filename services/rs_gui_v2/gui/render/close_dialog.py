"""Close dialog rendering and typed close-item model for rs_gui_v2."""

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Tuple

from ..view_models import ShellViewModel
from .shared import ACTION_BUTTON_WIDTH, COMPACT_BUTTON_WIDTH, PRIMARY_BUTTON_WIDTH, add_action_button


APP_CLOSE_MODAL_TAG = "rs_gui_v2_close_modal"
APP_CLOSE_STATUS_TAG = "rs_gui_v2_close_status"


@dataclass(frozen=True)
class CloseItem:
    """Typed model for one process tracked in the close dialog."""

    item_id: str
    kind: str
    name: str
    source: str = ""
    pid: str = ""
    hostname: str = ""
    state: str = "unknown"
    owned: bool = False
    active: bool = False

    @property
    def item_type(self) -> str:
        """Return 'record' or 'convert' from the item_id prefix."""
        return self.item_id.split(":", 1)[0] if ":" in self.item_id else ""

    @property
    def item_key(self) -> str:
        """Return the identifier portion after the type prefix."""
        return self.item_id.split(":", 1)[1] if ":" in self.item_id else self.item_id

    def display_text(self) -> str:
        ownership = "launched by this GUI" if self.owned else "detected externally"
        pid = self.pid.strip() or "unknown pid"
        location = f" on {self.hostname}" if self.hostname.strip() else ""
        return f"{self.kind}: {self.name} | {ownership} | {pid}{location} | {self.state}"


def close_process_items(view: ShellViewModel) -> Tuple[CloseItem, ...]:
    """Collect all tracked service processes from the current view snapshot."""

    items = []
    for row in view.record_tab.candidates:
        active = str(row.state).lower() not in ("exited", "start_failed", "stopped", "shutdown")
        items.append(CloseItem(
            item_id=f"record:{row.candidate_id}",
            kind="Recording Service",
            name=row.control_name,
            source=row.source,
            pid=str(row.pid) if row.pid else "",
            hostname=row.hostname,
            state=row.state,
            owned=bool(row.owned),
            active=active,
        ))
    convert = view.convert_tab
    if convert is not None:
        for job in convert.jobs:
            active = str(job.state).lower() in ("queued", "starting", "running", "cancel_requested")
            if not active:
                continue
            items.append(CloseItem(
                item_id=f"convert:{job.job_id}",
                kind="Converter Job",
                name=job.job_id,
                source="gui_launch",
                state=job.state,
                owned=True,
                active=True,
            ))
    return tuple(items)


def default_close_policy(view: ShellViewModel) -> Tuple[str, Tuple[str, ...]]:
    """Return the default close action and item IDs for unattended shutdown."""

    items = close_process_items(view)
    gui_owned_ids = tuple(item.item_id for item in items if item.owned and item.active)
    if gui_owned_ids:
        return "shutdown_gui_launched", gui_owned_ids
    return "leave_running", ()


def show_close_prompt(
        dpg,
        view: ShellViewModel,
        close_handler: Callable[[str, Tuple[str, ...]], bool],
) -> None:
    """Render the modal close-confirmation dialog."""

    delete_item = getattr(dpg, "delete_item", None)
    does_item_exist = getattr(dpg, "does_item_exist", None)
    if callable(delete_item) and callable(does_item_exist):
        try:
            if does_item_exist(APP_CLOSE_MODAL_TAG):
                delete_item(APP_CLOSE_MODAL_TAG)
        except Exception:
            pass

    items = close_process_items(view)
    gui_owned_item_ids = tuple(item.item_id for item in items if item.owned and item.active)
    with dpg.window(
            label="Close rs_gui_v2",
            tag=APP_CLOSE_MODAL_TAG,
            modal=True,
            show=True,
            no_close=True,
            width=720,
            height=360,
    ):
        dpg.add_text("Detected RTI service processes")
        if items:
            for item in items:
                dpg.add_text(item.display_text())
        else:
            dpg.add_text("No Recording Service or Converter processes are currently detected by this GUI.")
        dpg.add_separator()
        dpg.add_text("", tag=APP_CLOSE_STATUS_TAG)
        with dpg.group(horizontal=True):
            add_action_button(
                dpg,
                label="Leave Running",
                callback=_close_dialog_action_callback(dpg, close_handler, "leave_running", ()),
                width=ACTION_BUTTON_WIDTH,
            )
            add_action_button(
                dpg,
                label="Shutdown GUI-Launched",
                enabled=bool(gui_owned_item_ids),
                callback=_close_dialog_action_callback(dpg, close_handler, "shutdown_gui_launched", gui_owned_item_ids),
                width=PRIMARY_BUTTON_WIDTH,
            )
            add_action_button(
                dpg,
                label="Cancel",
                callback=_close_dialog_cancel_callback(dpg),
                width=COMPACT_BUTTON_WIDTH,
            )


def _close_dialog_action_callback(
        dpg,
        close_handler: Callable[[str, Tuple[str, ...]], bool],
        action: str,
        item_ids: Tuple[str, ...],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        _set_close_status(dpg, _close_action_status(action))
        _render_one_frame_if_possible(dpg)
        if close_handler(action, tuple(item_ids)):
            _set_close_status(dpg, "Cleanup complete. Closing...")
            _render_one_frame_if_possible(dpg)
            stop = getattr(dpg, "stop_dearpygui", None)
            if callable(stop):
                stop()
            return True
        _set_close_status(dpg, "Close canceled or failed.")
        return False
    return _callback


def _close_action_status(action: str) -> str:
    if action == "shutdown_gui_launched":
        return "Shutting down GUI-launched services..."
    if action == "leave_running":
        return "Leaving detected services running..."
    return "Closing..."


def _set_close_status(dpg, message: str) -> None:
    set_value = getattr(dpg, "set_value", None)
    if callable(set_value):
        try:
            set_value(APP_CLOSE_STATUS_TAG, str(message))
        except Exception:
            pass


def _render_one_frame_if_possible(dpg) -> None:
    render_frame = getattr(dpg, "render_dearpygui_frame", None)
    if callable(render_frame):
        try:
            render_frame()
        except Exception:
            pass


def _close_dialog_cancel_callback(dpg):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        delete_item = getattr(dpg, "delete_item", None)
        if callable(delete_item):
            try:
                delete_item(APP_CLOSE_MODAL_TAG)
            except Exception:
                pass
        return False
    return _callback
