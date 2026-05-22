"""View-model builders for rs_gui_v2 tabs."""

from .record_controller import RecordTabController, RecordTabControllerConfig
from .record_tab import (
    RecordActionView,
    RecordCandidateRow,
    RecordCommandRow,
    RecordTabViewModel,
    build_mock_record_tab_view_model,
    build_record_action_command,
    build_record_tab_view_model,
)
from .topics_tab import (
    SampleInspectorRow,
    TopicActionView,
    TopicFieldRow,
    TopicRow,
    TopicsTabViewModel,
    build_mock_topics_tab_view_model,
    build_topics_tab_view_model,
)

__all__ = [
    "RecordActionView",
    "RecordCandidateRow",
    "RecordCommandRow",
    "RecordTabController",
    "RecordTabControllerConfig",
    "RecordTabViewModel",
    "SampleInspectorRow",
    "TopicActionView",
    "TopicFieldRow",
    "TopicRow",
    "TopicsTabViewModel",
    "build_mock_record_tab_view_model",
    "build_mock_topics_tab_view_model",
    "build_record_action_command",
    "build_record_tab_view_model",
    "build_topics_tab_view_model",
]
