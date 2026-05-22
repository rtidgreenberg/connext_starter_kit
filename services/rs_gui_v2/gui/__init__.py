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
from .tabs import RecordTabController, RecordTabControllerConfig
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
    "ShellStatusItem",
    "ShellViewModel",
    "UiFrameScheduler",
    "build_default_gui_shell_session",
    "build_gui_shell_assembly",
    "build_mock_shell_view_model",
    "build_shell_view_model",
]
