"""Dear PyGui-facing shell helpers for rs_gui_v2."""

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
    "GuiShellSession",
    "GuiShellSessionConfig",
    "RecordTabController",
    "RecordTabControllerConfig",
    "ShellStatusItem",
    "ShellViewModel",
    "UiFrameScheduler",
    "build_mock_shell_view_model",
    "build_shell_view_model",
]
