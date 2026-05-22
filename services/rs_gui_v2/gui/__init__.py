"""Dear PyGui-facing shell helpers for rs_gui_v2."""

from .factory import (
    GuiShellAssembly,
    GuiShellSessionFactoryConfig,
    GuiShellSessionMode,
    build_default_gui_shell_session,
    build_gui_shell_assembly,
)
from .scheduler import UiFrameScheduler
from .session import GuiShellSession, GuiShellSessionConfig
from .tabs import (
    RecordTabController,
    RecordTabControllerConfig,
    TopicsTabController,
    TopicsTabControllerConfig,
)
from .tabs.topics_tab import (
    SampleInspectorRow,
    TopicActionView,
    TopicFieldRow,
    TopicRow,
    TopicsTabViewModel,
    build_mock_topics_tab_view_model,
    build_topics_tab_view_model,
)
from .view_models import (
    EventLogEntry,
    ShellStatusItem,
    ShellViewModel,
    build_mock_shell_view_model,
    build_shell_view_model,
)

__all__ = [
    "EventLogEntry",
    "GuiShellAssembly",
    "GuiShellSession",
    "GuiShellSessionConfig",
    "GuiShellSessionFactoryConfig",
    "GuiShellSessionMode",
    "RecordTabController",
    "RecordTabControllerConfig",
    "SampleInspectorRow",
    "ShellStatusItem",
    "ShellViewModel",
    "TopicActionView",
    "TopicFieldRow",
    "TopicRow",
    "TopicsTabController",
    "TopicsTabControllerConfig",
    "TopicsTabViewModel",
    "UiFrameScheduler",
    "build_default_gui_shell_session",
    "build_gui_shell_assembly",
    "build_mock_shell_view_model",
    "build_mock_topics_tab_view_model",
    "build_shell_view_model",
    "build_topics_tab_view_model",
]
