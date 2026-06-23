"""Dear PyGui application shell for rti_view."""

from dataclasses import dataclass, replace
import time
import traceback
from typing import Dict, List, Optional, Set, Tuple

from ..config import ViewConfig
from ..debug_log import debug
from ..discovery import DiscoveredEndpoint, create_participant, refresh_endpoints, refresh_participants, registry
from ..fields import enumerate_fields, enumerate_sample_fields, format_sample_items
from ..subscriber import FieldSampleBuffer, pump_reader_once, setup_matched_reader


DOMAIN_INPUT_TAG = "rti_view_domain_input"
PROCESS_LIST_TAG = "rti_view_process_list"
TOPIC_LIST_TAG = "rti_view_topic_list"
FIELD_LIST_TAG = "rti_view_field_list"
MODE_TOGGLE_TAG = "rti_view_mode_toggle"
MESSAGE_DATA_TAG = "rti_view_message_data"
PLOT_GROUP_TAG = "rti_view_plot_group"
PLOT_SERIES_TAG = "rti_view_plot_series"
PLOT_Y_AXIS_TAG = "rti_view_plot_y_axis"
PLOT_X_AXIS_TAG = "rti_view_plot_x_axis"
COMMAND_INPUT_TAG = "rti_view_command_input"
STATUS_TEXT_TAG = "rti_view_status_text"
DEBUG_LOG_TAG = "rti_view_debug_log"
FIELD_TREE_TAG = "rti_view_field_tree"
SUBSCRIBE_BUTTON_TAG = "rti_view_subscribe_button"


@dataclass(frozen=True)
class UiSelection:
    """Current user selection shown by the shell."""

    domain_id: int = 0
    process_label: str = ""
    topic_name: str = ""
    field_path: str = ""
    mode: str = "plot"
    history_seconds: int = 30

    def startup_command(self) -> str:
        return ViewConfig(
            domain_id=self.domain_id,
            topic_name=self.topic_name,
            field_path=self.field_path,
            mode=self.mode,
            history_seconds=self.history_seconds,
        ).to_startup_string()


@dataclass
class ActiveSubscription:
    """Interactive GUI subscription state."""

    endpoint: DiscoveredEndpoint
    field_path: str
    reader: object
    subscriber: object
    buffer: FieldSampleBuffer
    started_at: float
    last_sample: object = None


class RtiViewShell:
    """Minimal Dear PyGui shell with stable tags and command-copy behavior."""

    def __init__(
            self,
            initial_domain: int = 0,
            initial_topic: str = "",
            initial_field: str = "",
            initial_mode: str = "plot",
            history_seconds: int = 30,
            dpg_module=None,
    ) -> None:
        self._selection = UiSelection(
            domain_id=initial_domain,
            topic_name=initial_topic,
            field_path=initial_field,
            mode=initial_mode,
            history_seconds=history_seconds,
        )
        self._dpg = dpg_module
        self._participant = None
        self._participant_domain: Optional[int] = None
        self._last_refresh = 0.0
        self._participant_labels: Dict[str, str] = {}
        self._topic_endpoints: Dict[str, DiscoveredEndpoint] = {}
        self._field_choices: Tuple[str, ...] = ()
        self._last_field_status = ""
        self._subscription: Optional[ActiveSubscription] = None
        self._debug_lines: List[str] = []
        self._logged_topic_type_keys: Set[str] = set()
        self._direct_target = bool(initial_topic and initial_field)
        self._direct_target_failed = False

    @property
    def selection(self) -> UiSelection:
        return self._selection

    def run(self) -> None:
        dpg = self._dpg or _load_dearpygui()
        dpg.create_context()
        try:
            dpg.create_viewport(title="rti_view", width=1280, height=820)
            self.render(dpg)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            self._set_status(dpg, "Starting rti_view")
            self._ensure_participant(dpg)
            if hasattr(dpg, "is_dearpygui_running") and hasattr(dpg, "render_dearpygui_frame"):
                while dpg.is_dearpygui_running():
                    self._update_discovery_view(dpg)
                    self._pump_subscription(dpg)
                    dpg.render_dearpygui_frame()
            else:
                dpg.start_dearpygui()
        finally:
            self._close_participant()
            dpg.destroy_context()

    def render_once(self) -> None:
        dpg = self._dpg or _load_dearpygui()
        dpg.create_context()
        try:
            self.render(dpg)
        finally:
            dpg.destroy_context()

    def render(self, dpg) -> None:
        with dpg.window(label="rti_view", tag="rti_view_main", width=1280, height=820):
            self._render_top_bar(dpg)
            dpg.add_separator()
            with dpg.group(horizontal=True):
                self._render_list_panel(
                    dpg,
                    "Process / Participant",
                    PROCESS_LIST_TAG,
                    ("No participants discovered",),
                    self._participant_callback(dpg),
                )
                self._render_list_panel(
                    dpg,
                    "Writer Topics",
                    TOPIC_LIST_TAG,
                    ("Select a process",),
                    self._topic_callback(dpg),
                )
                self._render_list_panel(
                    dpg,
                    "Fields",
                    FIELD_LIST_TAG,
                    ("Select a writer topic",),
                    self._field_callback(dpg),
                )
            dpg.add_separator()
            self._render_field_view(dpg)
            dpg.add_separator()
            self._render_command_bar(dpg)
            dpg.add_text("Ready", tag=STATUS_TEXT_TAG)
            self._render_debug_log(dpg)

    def _render_top_bar(self, dpg) -> None:
        with dpg.group(horizontal=True):
            dpg.add_text("Domain")
            dpg.add_input_int(
                tag=DOMAIN_INPUT_TAG,
                width=100,
                default_value=self._selection.domain_id,
                callback=self._domain_callback(dpg),
            )
            dpg.add_button(label="Refresh", width=100, callback=self._refresh_callback(dpg))

    def _render_list_panel(self, dpg, label: str, tag: str, items: Tuple[str, ...], callback) -> None:
        with dpg.child_window(label=label, width=300, height=220, border=True):
            dpg.add_text(label)
            dpg.add_listbox(items=list(items), tag=tag, width=-1, num_items=8, callback=callback)

    def _render_field_view(self, dpg) -> None:
        with dpg.group(horizontal=True):
            dpg.add_text("Display")
            dpg.add_radio_button(
                items=["Message Data", "Plot"],
                tag=MODE_TOGGLE_TAG,
                horizontal=True,
                default_value="Plot" if self._selection.mode == "plot" else "Message Data",
                callback=self._mode_callback(dpg),
            )
            dpg.add_button(
                label="Subscribe",
                tag=SUBSCRIBE_BUTTON_TAG,
                width=120,
                callback=self._subscribe_callback(dpg),
            )
        with dpg.child_window(label="Data Type", tag=FIELD_TREE_TAG, height=160, border=True):
            dpg.add_text("Select a writer topic")
        with dpg.child_window(label="Field View", height=330, border=True):
            dpg.add_text("", tag=MESSAGE_DATA_TAG, show=(self._selection.mode != "plot"))
            with dpg.group(tag=PLOT_GROUP_TAG, show=(self._selection.mode == "plot")):
                with dpg.plot(label="Plot", height=290, width=-1):
                    dpg.add_plot_axis(dpg.mvXAxis, label="Time", tag=PLOT_X_AXIS_TAG)
                    y_axis = dpg.add_plot_axis(dpg.mvYAxis, label="Value", tag=PLOT_Y_AXIS_TAG)
                    dpg.add_line_series([], [], label="selected field", tag=PLOT_SERIES_TAG, parent=y_axis)

    def _render_command_bar(self, dpg) -> None:
        with dpg.group(horizontal=True):
            dpg.add_input_text(
                tag=COMMAND_INPUT_TAG,
                default_value=self._selection.startup_command(),
                readonly=True,
                width=900,
            )
            dpg.add_button(label="Copy", width=90, callback=self._copy_command_callback(dpg))

    def _render_debug_log(self, dpg) -> None:
        with dpg.child_window(label="Debug Log", height=140, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("Debug Log")
                dpg.add_button(label="Copy Debug Log", width=140, callback=self._copy_debug_log_callback(dpg))
                dpg.add_button(label="Clear", width=70, callback=self._clear_debug_log_callback(dpg))
            dpg.add_input_text(
                tag=DEBUG_LOG_TAG,
                default_value=self.debug_log_text,
                multiline=True,
                readonly=True,
                width=-1,
                height=92,
            )

    @property
    def debug_log_text(self) -> str:
        return "\n".join(self._debug_lines)

    def _set_selection(self, dpg, selection: UiSelection) -> None:
        self._selection = selection
        set_value = getattr(dpg, "set_value", None)
        if callable(set_value):
            set_value(COMMAND_INPUT_TAG, self._selection.startup_command())

    def _ensure_participant(self, dpg) -> None:
        if self._participant is not None and self._participant_domain == self._selection.domain_id:
            return
        self._close_participant()
        registry.clear()
        try:
            self._participant = create_participant(self._selection.domain_id)
            self._participant_domain = self._selection.domain_id
            self._last_refresh = 0.0
            self._logged_topic_type_keys.clear()
            self._set_status(dpg, f"Listening on domain {self._selection.domain_id}")
        except Exception as exc:
            self._participant = None
            self._participant_domain = None
            self._set_exception_status(dpg, f"Failed to open domain {self._selection.domain_id}: {exc}")

    def _close_participant(self) -> None:
        participant = self._participant
        self._participant = None
        self._participant_domain = None
        close = getattr(participant, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        self._close_subscription()

    def _update_discovery_view(self, dpg, force: bool = False) -> None:
        if self._participant is None:
            return
        now = time.monotonic()
        if not force and now - self._last_refresh < 0.5:
            return
        self._last_refresh = now
        try:
            refresh_endpoints(self._participant)
            refresh_participants(self._participant)
        except Exception as exc:
            self._set_exception_status(dpg, f"Discovery refresh failed: {exc}")
            return

        participant_labels = []
        self._participant_labels.clear()
        for participant in registry.participants():
            label = f"{participant.label} [{participant.key}]"
            participant_labels.append(label)
            self._participant_labels[label] = participant.key
        self._configure_list(dpg, PROCESS_LIST_TAG, tuple(participant_labels), "No participants discovered")
        self._log_discovered_topic_types(dpg)

        selected_process = self._get_value(dpg, PROCESS_LIST_TAG)
        participant_key = self._participant_labels.get(selected_process, "")
        topic_names = registry.topics_for_participant(participant_key) if participant_key else ()
        self._topic_endpoints = registry.writer_by_topic_for_participant(participant_key) if participant_key else {}
        topic_empty_label = "Select a process"
        if not participant_key and self._direct_target:
            direct_endpoint, _diagnostics = registry.select_writer_for_topic(self._selection.topic_name)
            if direct_endpoint is not None:
                self._topic_endpoints = {direct_endpoint.topic_name: direct_endpoint}
                topic_names = (direct_endpoint.topic_name,)
                topic_empty_label = "Waiting for requested writer topic"
            else:
                topic_names = ()
                topic_empty_label = "Waiting for requested writer topic"
        self._configure_list(dpg, TOPIC_LIST_TAG, topic_names, topic_empty_label)

        selected_topic = self._get_value(dpg, TOPIC_LIST_TAG)
        if selected_topic not in self._topic_endpoints:
            selected_topic = self._selection.topic_name if self._direct_target else ""
        endpoint = self._topic_endpoints.get(selected_topic)
        field_names, field_empty_label = self._field_state(selected_topic, endpoint)
        self._field_choices = field_names
        self._configure_list(dpg, FIELD_LIST_TAG, field_names, field_empty_label)
        self._sync_field_tree(dpg, endpoint, field_names, field_empty_label)
        self._set_field_status_if_changed(dpg, selected_topic, field_names, field_empty_label)

        field_path = self._selection.field_path
        if field_names and field_path not in field_names:
            field_path = ""
        self._set_selection(dpg, replace(
            self._selection,
            process_label=selected_process if selected_process in self._participant_labels else "",
            topic_name=selected_topic if selected_topic else self._selection.topic_name,
            field_path=field_path,
        ))
        self._maybe_auto_subscribe_direct_view(dpg, endpoint, field_names)

    def _configure_list(self, dpg, tag: str, items: Tuple[str, ...], empty_label: str) -> None:
        item_values = list(items) if items else [empty_label]
        configure_item = getattr(dpg, "configure_item", None)
        set_value = getattr(dpg, "set_value", None)
        get_value = getattr(dpg, "get_value", None)
        if callable(configure_item):
            configure_item(tag, items=item_values)
        if callable(set_value):
            current = get_value(tag) if callable(get_value) else None
            if current not in item_values:
                set_value(tag, item_values[0])

    def _field_names(self, endpoint: Optional[DiscoveredEndpoint]) -> Tuple[str, ...]:
        if endpoint is None or endpoint.dynamic_type is None:
            return ()
        try:
            return tuple(field.path for field in enumerate_fields(endpoint.dynamic_type))
        except Exception:
            return ()

    def _field_state(
            self,
            selected_topic: str,
            endpoint: Optional[DiscoveredEndpoint],
    ) -> Tuple[Tuple[str, ...], str]:
        if not selected_topic:
            return (), "Select a writer topic"
        if endpoint is None:
            return (), f"No writer endpoint found for '{selected_topic}'"
        if endpoint.dynamic_type is None:
            return (), f"Waiting for type information for '{selected_topic}'"
        try:
            field_names = tuple(field.path for field in enumerate_fields(endpoint.dynamic_type))
        except Exception as exc:
            type_name = endpoint.type_name or selected_topic
            return (), f"Field enumeration failed for '{type_name}': {exc}"
        if not field_names:
            type_name = endpoint.type_name or selected_topic
            return (), f"No fields found for '{type_name}'"
        return field_names, "Select a field"

    def _set_field_status_if_changed(
            self,
            dpg,
            selected_topic: str,
            field_names: Tuple[str, ...],
            message: str,
    ) -> None:
        if field_names or not selected_topic:
            self._last_field_status = ""
            return
        if message != self._last_field_status:
            self._last_field_status = message
            self._set_status(dpg, message)

    def _sync_field_tree(
            self,
            dpg,
            endpoint: Optional[DiscoveredEndpoint],
            field_names: Tuple[str, ...],
            empty_label: str,
    ) -> None:
        does_item_exist = getattr(dpg, "does_item_exist", None)
        if callable(does_item_exist) and not does_item_exist(FIELD_TREE_TAG):
            return
        delete_item = getattr(dpg, "delete_item", None)
        add_text = getattr(dpg, "add_text", None)
        if callable(delete_item):
            delete_item(FIELD_TREE_TAG, children_only=True)
        if not field_names:
            if callable(add_text):
                add_text(empty_label, parent=FIELD_TREE_TAG)
            return
        type_label = endpoint.type_name if endpoint and endpoint.type_name else endpoint.topic_name if endpoint else "Data Type"
        self._render_field_tree_node(dpg, FIELD_TREE_TAG, type_label, _field_tree(field_names), root=True)

    def _render_field_tree_node(self, dpg, parent, label: str, node: Dict[str, object], root: bool = False) -> None:
        tree_node = getattr(dpg, "tree_node", None)
        add_selectable = getattr(dpg, "add_selectable", None)
        add_text = getattr(dpg, "add_text", None)
        leaf_path = node.get("__path__")
        child_names = sorted(name for name in node if name != "__path__")
        if leaf_path and not child_names:
            if callable(add_selectable):
                kwargs = {
                    "label": label,
                    "default_value": leaf_path == self._selection.field_path,
                    "callback": self._field_tree_callback(dpg),
                    "user_data": leaf_path,
                }
                if parent is not None:
                    kwargs["parent"] = parent
                add_selectable(**kwargs)
            return
        if callable(tree_node):
            kwargs = {"label": label, "default_open": root}
            if parent is not None:
                kwargs["parent"] = parent
            with tree_node(**kwargs):
                for child_name in child_names:
                    self._render_field_tree_node(dpg, None, child_name, node[child_name])
            return
        if callable(add_text):
            add_text(label, parent=parent)
            for child_name in child_names:
                child = node[child_name]
                child_path = child.get("__path__") if isinstance(child, dict) else ""
                add_text(f"  {child_path or child_name}", parent=parent)

    def _field_tree_callback(self, dpg):
        def _callback(_sender=None, _app_data=None, user_data=None):
            field_path = str(user_data or "")
            if field_path not in self._field_choices:
                return False
            set_value = getattr(dpg, "set_value", None)
            if callable(set_value):
                set_value(FIELD_LIST_TAG, field_path)
            self._set_selection(dpg, replace(self._selection, field_path=field_path))
            if self._subscription is not None:
                self._subscription.field_path = field_path
                self._subscription.buffer = FieldSampleBuffer()
            return True
        return _callback

    def _subscribe_callback(self, dpg):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            return self._subscribe_selected_field(dpg)
        return _callback

    def _subscribe_selected_field(self, dpg) -> bool:
        if self._participant is None:
            self._set_status(dpg, "Open a DDS domain before subscribing")
            return False
        endpoint = self._topic_endpoints.get(self._selection.topic_name)
        if endpoint is None:
            self._set_status(dpg, "Select a writer topic before subscribing")
            return False

        # Auto-select first plottable field if none selected
        field_path = self._selection.field_path
        if not field_path and endpoint.dynamic_type is not None:
            try:
                fields = enumerate_fields(endpoint.dynamic_type)
                plottable = next((f for f in fields if f.plottable), None)
                if plottable:
                    field_path = plottable.path
                    self._set_selection(dpg, replace(self._selection, field_path=field_path))
                    set_value = getattr(dpg, "set_value", None)
                    if callable(set_value):
                        set_value(FIELD_LIST_TAG, field_path)
            except Exception:
                pass

        debug("subscribe", f"topic={endpoint.topic_name} field_path={field_path!r} type_available={endpoint.type_available}")
        result = setup_matched_reader(self._participant, endpoint)
        if not result.ok:
            message = result.diagnostic.message if result.diagnostic else "Reader setup failed"
            debug("subscribe", f"FAILED: {message}")
            self._set_status(dpg, message)
            return False
        self._close_subscription()
        self._subscription = ActiveSubscription(
            endpoint=endpoint,
            field_path=field_path,
            reader=result.reader,
            subscriber=result.subscriber,
            buffer=FieldSampleBuffer(),
            started_at=time.time(),
        )
        suffix = f".{field_path}" if field_path else ""
        debug("subscribe", f"OK: reader created, field_path={field_path!r}, mode={self._selection.mode}")
        self._set_status(dpg, f"Subscribed to {endpoint.topic_name}{suffix}")
        return True

    def _pump_subscription(self, dpg) -> None:
        if self._subscription is None:
            return
        try:
            accepted = self._pump_selected_or_sample_items(dpg)
        except Exception as exc:
            debug("pump", f"EXCEPTION: {exc}")
            self._set_exception_status(dpg, f"Subscription read failed: {exc}")
            self._close_subscription()
            return
        if accepted:
            debug("pump", f"accepted={accepted} field_path={self._subscription.field_path!r} msgs={len(self._subscription.buffer.messages)} pts={len(self._subscription.buffer.points)} skipped_non_numeric={self._subscription.buffer.skipped_non_numeric}")
            self._sync_subscription_view(dpg)

    def _pump_selected_or_sample_items(self, dpg) -> int:
        if self._subscription is None:
            return 0
        if self._subscription.field_path:
            return pump_reader_once(
                self._subscription.reader,
                self._subscription.field_path,
                self._subscription.buffer,
            )
        accepted = 0
        for sample, info in self._subscription.reader.take():
            if not getattr(info, "valid", False):
                self._subscription.buffer.append_invalid()
                continue
            self._subscription.last_sample = sample
            self._sync_fields_from_sample(dpg, sample)
            accepted += 1
        return accepted

    def _sync_fields_from_sample(self, dpg, sample) -> None:
        sample_fields = tuple(field.path for field in enumerate_sample_fields(sample))
        if not sample_fields:
            return
        self._field_choices = sample_fields
        self._configure_list(dpg, FIELD_LIST_TAG, sample_fields, "Select a sample field")
        self._sync_field_tree(dpg, self._subscription.endpoint if self._subscription else None, sample_fields, "Select a sample field")

    def _sync_subscription_view(self, dpg) -> None:
        set_value = getattr(dpg, "set_value", None)
        if not callable(set_value) or self._subscription is None:
            debug("sync_view", f"SKIP: set_value={set_value is not None} subscription={self._subscription is not None}")
            return
        messages = self._subscription.buffer.messages[-12:]
        if messages:
            lines = [
                f"[{row.timestamp:.3f}] {self._subscription.endpoint.topic_name}."
                f"{self._subscription.field_path} = {row.value}"
                for row in messages
            ]
            set_value(MESSAGE_DATA_TAG, "\n".join(lines))
            debug("sync_view", f"text updated: {len(messages)} messages, last_value={messages[-1].value!r} type={type(messages[-1].value).__name__}")
        points = self._subscription.buffer.points
        if points:
            x_data = [point.timestamp - points[0].timestamp for point in points]
            y_data = [point.value for point in points]
            debug("sync_view", f"PLOT UPDATE: {len(points)} points, x_range=[{x_data[0]:.3f},{x_data[-1]:.3f}], y_range=[{min(y_data):.2f},{max(y_data):.2f}]")
            set_value(PLOT_SERIES_TAG, [x_data, y_data])
            fit_axis = getattr(dpg, "fit_axis_data", None)
            if callable(fit_axis):
                fit_axis(PLOT_X_AXIS_TAG)
                fit_axis(PLOT_Y_AXIS_TAG)
                debug("sync_view", "fit_axis_data called on both axes")
            else:
                debug("sync_view", "WARNING: fit_axis_data not available in dpg")
        elif self._subscription.last_sample is not None:
            debug("sync_view", f"NO POINTS - showing raw sample (msgs={len(messages)}, skipped_non_numeric={self._subscription.buffer.skipped_non_numeric})")
            lines = format_sample_items(self._subscription.last_sample)
            if lines:
                set_value(MESSAGE_DATA_TAG, "\n".join(lines[:80]))

    def _maybe_auto_subscribe_direct_view(
            self,
            dpg,
            endpoint: Optional[DiscoveredEndpoint],
            field_names: Tuple[str, ...],
    ) -> None:
        if not self._direct_target or self._direct_target_failed:
            return
        if endpoint is None or endpoint.topic_name != self._selection.topic_name:
            return
        if not field_names:
            return
        if self._selection.field_path not in field_names:
            self._direct_target_failed = True
            self._set_status(
                dpg,
                f"Field '{self._selection.field_path}' was not found in topic '{self._selection.topic_name}'",
            )
            return
        if self._subscription is not None:
            if self._subscription.endpoint.topic_name == endpoint.topic_name and self._subscription.field_path == self._selection.field_path:
                self._direct_target = False
                return
        if self._subscribe_selected_field(dpg):
            self._direct_target = False

    def _close_subscription(self) -> None:
        subscription = self._subscription
        self._subscription = None
        if subscription is None:
            return
        for entity in (subscription.reader, subscription.subscriber):
            close = getattr(entity, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def _log_discovered_topic_types(self, dpg) -> None:
        for endpoint in registry.endpoints.values():
            if not endpoint.is_writer or endpoint.key in self._logged_topic_type_keys:
                continue
            self._logged_topic_type_keys.add(endpoint.key)
            self._append_debug_line(
                dpg,
                f"Discovered writer topic '{endpoint.topic_name}' with type '{endpoint.type_name}'",
            )
            self._append_debug_block(dpg, self._format_topic_type_debug(endpoint))

    def _format_topic_type_debug(self, endpoint: DiscoveredEndpoint) -> str:
        dynamic_type = endpoint.dynamic_type
        if dynamic_type is None:
            lines = ["  DynamicType: unavailable from discovery"]
            if endpoint.type_debug:
                lines.append("  Builtin type fields:")
                lines.extend(f"  - {line}" for line in endpoint.type_debug[:12])
                if len(endpoint.type_debug) > 12:
                    lines.append(f"  ... {len(endpoint.type_debug) - 12} more type fields")
            return "\n".join(lines)

        type_name = self._dynamic_type_name(dynamic_type) or endpoint.type_name or "<unnamed>"
        lines = [f"  DynamicType: {type_name}"]
        try:
            fields = enumerate_fields(dynamic_type)
        except Exception as exc:
            return "\n".join(lines + [f"  Fields: failed to enumerate: {exc}"])

        if not fields:
            return "\n".join(lines + ["  Fields: none"])

        max_fields = 20
        for field in fields[:max_fields]:
            plot_marker = " plottable" if field.plottable else ""
            lines.append(f"  - {field.path}: {field.type_kind}{plot_marker}")
        if len(fields) > max_fields:
            lines.append(f"  ... {len(fields) - max_fields} more fields")
        return "\n".join(lines)

    def _dynamic_type_name(self, dynamic_type) -> str:
        try:
            return str(getattr(dynamic_type, "name", "") or "")
        except Exception:
            return ""

    def _get_value(self, dpg, tag: str) -> str:
        get_value = getattr(dpg, "get_value", None)
        if callable(get_value):
            value = get_value(tag)
            return str(value) if value is not None else ""
        return ""

    def _domain_callback(self, dpg):
        def _callback(_sender=None, app_data=None, _user_data=None):
            try:
                domain_id = int(app_data)
            except Exception:
                domain_id = self._selection.domain_id
            self._set_selection(dpg, replace(self._selection, domain_id=domain_id))
            self._ensure_participant(dpg)
        return _callback

    def _participant_callback(self, dpg):
        def _callback(_sender=None, app_data=None, _user_data=None):
            self._set_selection(dpg, replace(self._selection, process_label=str(app_data or ""), topic_name="", field_path=""))
            self._update_discovery_view(dpg, force=True)
        return _callback

    def _topic_callback(self, dpg):
        def _callback(_sender=None, app_data=None, _user_data=None):
            self._set_selection(dpg, replace(self._selection, topic_name=str(app_data or ""), field_path=""))
            self._update_discovery_view(dpg, force=True)
        return _callback

    def _field_callback(self, dpg):
        def _callback(_sender=None, app_data=None, _user_data=None):
            field_path = str(app_data or "")
            if field_path not in self._field_choices:
                field_path = ""
            debug("field_select", f"field_path={field_path!r} subscription_active={self._subscription is not None}")
            self._set_selection(dpg, replace(self._selection, field_path=field_path))
            if self._subscription is not None:
                self._subscription.field_path = field_path
                self._subscription.buffer = FieldSampleBuffer()
                debug("field_select", f"subscription field_path updated, buffer reset")
        return _callback

    def _refresh_callback(self, dpg):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            self._ensure_participant(dpg)
            self._update_discovery_view(dpg, force=True)
            self._set_status(dpg, f"Refreshed domain {self._selection.domain_id}")
        return _callback

    def _mode_callback(self, dpg):
        def _callback(_sender=None, app_data=None, _user_data=None):
            mode = "plot" if app_data == "Plot" else "text"
            debug("mode", f"mode changed to {mode!r}")
            self._set_selection(dpg, replace(self._selection, mode=mode))
            configure_item = getattr(dpg, "configure_item", None)
            if callable(configure_item):
                configure_item(MESSAGE_DATA_TAG, show=(mode != "plot"))
                configure_item(PLOT_GROUP_TAG, show=(mode == "plot"))
            if self._subscription is not None:
                self._sync_subscription_view(dpg)
        return _callback

    def _copy_command_callback(self, dpg):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            command = self._selection.startup_command()
            set_clipboard = getattr(dpg, "set_clipboard_text", None)
            if callable(set_clipboard):
                set_clipboard(command)
            self._set_status(dpg, "Copied startup command")
        return _callback

    def _copy_debug_log_callback(self, dpg):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            set_clipboard = getattr(dpg, "set_clipboard_text", None)
            if callable(set_clipboard):
                set_clipboard(self.debug_log_text)
            self._set_status(dpg, "Copied debug log")
        return _callback

    def _clear_debug_log_callback(self, dpg):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            self._debug_lines.clear()
            self._sync_debug_log(dpg)
            self._set_status(dpg, "Cleared debug log")
        return _callback

    def _status_callback(self, dpg, message: str):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            self._set_status(dpg, message)
        return _callback

    def _set_status(self, dpg, message: str) -> None:
        self._append_debug_line(dpg, message)
        set_value = getattr(dpg, "set_value", None)
        if callable(set_value):
            set_value(STATUS_TEXT_TAG, message)

    def _set_exception_status(self, dpg, message: str) -> None:
        self._set_status(dpg, message)
        self._append_debug_block(dpg, traceback.format_exc().rstrip())

    def _append_debug_line(self, dpg, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self._debug_lines.append(f"[{timestamp}] {message}")
        self._debug_lines = self._debug_lines[-300:]
        self._sync_debug_log(dpg)

    def _append_debug_block(self, dpg, text: str) -> None:
        if text:
            self._debug_lines.extend(text.splitlines())
            self._debug_lines = self._debug_lines[-300:]
            self._sync_debug_log(dpg)

    def _sync_debug_log(self, dpg) -> None:
        set_value = getattr(dpg, "set_value", None)
        does_item_exist = getattr(dpg, "does_item_exist", None)
        if callable(set_value) and (not callable(does_item_exist) or does_item_exist(DEBUG_LOG_TAG)):
            set_value(DEBUG_LOG_TAG, self.debug_log_text)


def _load_dearpygui():
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception as exc:
        raise RuntimeError(
            "Dear PyGui is required to run rti_view. Install dearpygui in this Python environment."
        ) from exc


def run_interactive(
        domain_id: int = 0,
        topic_name: str = "",
        field_path: str = "",
        mode: str = "plot",
        history_seconds: int = 30,
) -> None:
    """Launch the Dear PyGui interactive application."""
    RtiViewShell(
        initial_domain=domain_id,
        initial_topic=topic_name,
        initial_field=field_path,
        initial_mode=mode,
        history_seconds=history_seconds,
    ).run()


def _field_tree(field_paths: Tuple[str, ...]) -> Dict[str, object]:
    tree: Dict[str, object] = {}
    for field_path in field_paths:
        node = tree
        parts = tuple(part for part in str(field_path).split(".") if part)
        for part in parts:
            child = node.setdefault(part, {})
            node = child
        if parts:
            node["__path__"] = field_path
    return tree
