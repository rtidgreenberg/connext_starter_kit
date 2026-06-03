"""Shared test doubles for rs_gui_v2 headless tests.

Canonical implementations of FakeContext, FakeDpg, FakeHandle, and FakeSpawner.
Import from here instead of duplicating across test files.
"""


class FakeContext:
    """Fake context manager for DPG container calls (window, tab, group, table)."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeDpg:
    """Minimal Dear PyGui shim for headless rendering tests.

    Records all calls and stores widget tag values for later inspection.
    """

    def __init__(self):
        self.calls = []
        self.values = {}
        self.clipboard_text = ""
        self.context_created = False
        self.context_destroyed = False
        self.stopped = False
        self.exit_callback = None
        self.viewport_close_callback = None

    def create_context(self):
        self.context_created = True
        self.calls.append(("create_context", (), {}))

    def destroy_context(self):
        self.context_destroyed = True
        self.calls.append(("destroy_context", (), {}))

    def stop_dearpygui(self):
        self.stopped = True
        self.calls.append(("stop_dearpygui", (), {}))

    def create_viewport(self, *args, **kwargs):
        self.calls.append(("create_viewport", args, kwargs))

    def set_exit_callback(self, callback):
        self.exit_callback = callback
        self.calls.append(("set_exit_callback", (callback,), {}))

    def set_viewport_close_callback(self, callback):
        self.viewport_close_callback = callback
        self.calls.append(("set_viewport_close_callback", (callback,), {}))

    def setup_dearpygui(self):
        self.calls.append(("setup_dearpygui", (), {}))

    def show_viewport(self):
        self.calls.append(("show_viewport", (), {}))

    def start_dearpygui(self):
        self.calls.append(("start_dearpygui", (), {}))
        if self.exit_callback is not None:
            self.exit_callback()

    def window(self, *args, **kwargs):
        self.calls.append(("window", args, kwargs))
        return FakeContext()

    def tab_bar(self, *args, **kwargs):
        self.calls.append(("tab_bar", args, kwargs))
        return FakeContext()

    def tab(self, *args, **kwargs):
        self.calls.append(("tab", args, kwargs))
        return FakeContext()

    def group(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = ""
        self.calls.append(("group", args, kwargs))
        return FakeContext()

    def table(self, *args, **kwargs):
        self.calls.append(("table", args, kwargs))
        return FakeContext()

    def table_row(self, *args, **kwargs):
        self.calls.append(("table_row", args, kwargs))
        return FakeContext()

    def collapsing_header(self, *args, **kwargs):
        self.calls.append(("collapsing_header", args, kwargs))
        return FakeContext()

    def add_text(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = args[0] if args else kwargs.get("default_value", "")
        self.calls.append(("add_text", args, kwargs))

    def add_combo(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = kwargs.get("default_value", "")
        self.calls.append(("add_combo", args, kwargs))

    def add_button(self, *args, **kwargs):
        self.calls.append(("add_button", args, kwargs))

    def add_input_text(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = kwargs.get("default_value", "")
        self.calls.append(("add_input_text", args, kwargs))

    def add_checkbox(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = kwargs.get("default_value", False)
        self.calls.append(("add_checkbox", args, kwargs))

    def set_value(self, tag, value):
        self.values[tag] = value
        self.calls.append(("set_value", (tag, value), {}))

    def set_clipboard_text(self, value):
        self.clipboard_text = value
        self.calls.append(("set_clipboard_text", (value,), {}))

    def configure_item(self, tag, **kwargs):
        self.calls.append(("configure_item", (tag,), kwargs))

    def does_item_exist(self, tag):
        return tag in self.values

    def delete_item(self, tag, **kwargs):
        self.calls.append(("delete_item", (tag,), kwargs))

    def push_container_stack(self, tag):
        self.calls.append(("push_container_stack", (tag,), {}))

    def pop_container_stack(self):
        self.calls.append(("pop_container_stack", (), {}))

    def get_value(self, tag):
        return self.values.get(tag)

    def add_separator(self, *args, **kwargs):
        self.calls.append(("add_separator", args, kwargs))

    def add_table_column(self, *args, **kwargs):
        self.calls.append(("add_table_column", args, kwargs))


class NoViewportCloseFakeDpg(FakeDpg):
    """FakeDpg variant where set_viewport_close_callback is absent (old DPG)."""

    set_viewport_close_callback = None


class ManualFrameFakeDpg(FakeDpg):
    """FakeDpg that simulates a fixed number of manual render frames."""

    def __init__(self, frame_count=2):
        super().__init__()
        self.frame_count = int(frame_count)
        self.rendered_frames = 0

    def is_dearpygui_running(self):
        return self.rendered_frames < self.frame_count

    def render_dearpygui_frame(self):
        self.rendered_frames += 1
        self.calls.append(("render_dearpygui_frame", (), {}))


class FakeHandle:
    """Fake process handle for ServiceProcessManager tests."""

    def __init__(self, pid=4321, output_path=""):
        self.pid = pid
        self.returncode = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.output_path = output_path

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9


class FakeSpawner:
    """Fake process spawner that yields queued FakeHandle instances."""

    def __init__(self, *handles):
        self.handles = list(handles)
        self.calls = []

    def start(self, command_line, working_dir="", environment=None):
        self.calls.append(tuple(command_line))
        if not self.handles:
            raise RuntimeError("no fake handles queued")
        return self.handles.pop(0)
