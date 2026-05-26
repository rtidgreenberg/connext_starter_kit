"""GUI workspace projection and command handling for rs_gui_v2."""

import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from app_core import (
    AppCommand,
    CommandResult,
    CommandStatus,
    TopicSelectionState,
    WorkspaceDocument,
    WorkspacePlotDefinition,
    load_workspace,
    save_workspace,
)

from .tabs import ConvertTabController, PlotsTabController, TopicsTabController


GUI_WORKSPACE_METADATA_KEY = "gui"


@dataclass(frozen=True)
class GuiWorkspaceControllerConfig:
    """Workspace file behavior for the GUI shell."""

    default_path: str = ""


class GuiWorkspaceController:
    """Project GUI intent to and from DDS-free workspace documents."""

    def __init__(
            self,
            topics_controller: Optional[TopicsTabController] = None,
            plots_controller: Optional[PlotsTabController] = None,
            convert_controller: Optional[ConvertTabController] = None,
            config: Optional[GuiWorkspaceControllerConfig] = None,
            clock=time.time,
    ) -> None:
        self._convert_controller = convert_controller
        self._topics_controller = topics_controller
        self._plots_controller = plots_controller
        self._config = config or GuiWorkspaceControllerConfig()
        self._clock = clock
        self._last_document: Optional[WorkspaceDocument] = None
        self._last_path = ""

    @property
    def last_document(self) -> Optional[WorkspaceDocument]:
        return self._last_document

    @property
    def last_path(self) -> str:
        return self._last_path

    @property
    def current_path(self) -> str:
        return self._last_path or self._config.default_path

    def build_document(
            self,
            workspace_name: str = "",
            path: str = "",
    ) -> WorkspaceDocument:
        """Return a persistable document from current GUI controller intent."""

        topic_selections = self._topic_selections()
        subscriptions = self._subscriptions()
        plots = self._plots()
        document = WorkspaceDocument(
            name=workspace_name,
            domains=_workspace_domains(topic_selections, subscriptions, plots),
            topic_selections=topic_selections,
            subscriptions=subscriptions,
            plots=plots,
            recent_files=(path,) if path else (),
            metadata={GUI_WORKSPACE_METADATA_KEY: self._gui_metadata()},
        )
        self._last_document = document
        return document

    def apply_document(self, document: WorkspaceDocument) -> WorkspaceDocument:
        """Restore GUI controller intent from a loaded workspace document."""

        gui_metadata = dict(document.metadata.get(GUI_WORKSPACE_METADATA_KEY, {}))
        if self._convert_controller is not None:
            self._convert_controller.apply_workspace_intent(
                metadata=gui_metadata.get("convert", {}),
            )
        if self._topics_controller is not None:
            self._topics_controller.apply_workspace_intent(
                document.topic_selections,
                subscriptions=document.subscriptions,
                metadata=gui_metadata.get("topics", {}),
            )
        if self._plots_controller is not None:
            self._plots_controller.apply_workspace_intent(
                document.plots,
                metadata=gui_metadata.get("plots", {}),
            )
        self._last_document = document
        return document

    def save(
            self,
            path: str,
            workspace_name: str = "",
    ) -> WorkspaceDocument:
        """Save current GUI intent to a workspace JSON file."""

        path = str(path)
        if not path:
            raise ValueError("workspace.save requires a path")
        document = self.build_document(workspace_name=workspace_name, path=path)
        save_workspace(document, path)
        self._last_path = path
        return document

    def load(self, path: str) -> WorkspaceDocument:
        """Load a workspace JSON file and restore GUI intent."""

        path = str(path)
        if not path:
            raise ValueError("workspace.load requires a path")
        document = load_workspace(path)
        self.apply_document(document)
        self._last_path = path
        return document

    def handle_command(
            self,
            command: AppCommand,
            workspace_name: str = "",
    ) -> CommandResult:
        """Handle workspace.save and workspace.load commands from the GUI queue."""

        payload = dict(command.payload)
        if command.command_type == "workspace.save":
            path = str(payload.get("path") or self._config.default_path)
            name = str(payload.get("workspace_name") or workspace_name)
            document = self.save(path, workspace_name=name)
            return _command_result(command, f"Saved workspace {document.name}", document, path)
        if command.command_type == "workspace.load":
            path = str(payload.get("path") or self._config.default_path)
            document = self.load(path)
            return _command_result(command, f"Loaded workspace {document.name}", document, path)
        raise ValueError(f"Unsupported workspace command type: {command.command_type}")

    def _topic_selections(self) -> TopicSelectionState:
        if self._topics_controller is None:
            return TopicSelectionState()
        return self._topics_controller.workspace_topic_selections()

    def _subscriptions(self):
        if self._topics_controller is None:
            return ()
        return self._topics_controller.workspace_subscription_requests()

    def _plots(self) -> Tuple[WorkspacePlotDefinition, ...]:
        if self._plots_controller is None:
            return ()
        return self._plots_controller.workspace_plot_definitions()

    def _gui_metadata(self) -> Mapping[str, Any]:
        metadata = {"saved_at": self._clock()}
        if self._convert_controller is not None:
            metadata["convert"] = dict(self._convert_controller.workspace_config())
        if self._topics_controller is not None:
            metadata["topics"] = dict(self._topics_controller.workspace_metadata())
        if self._plots_controller is not None:
            metadata["plots"] = dict(self._plots_controller.workspace_metadata())
        return metadata


def _command_result(
        command: AppCommand,
        message: str,
        document: WorkspaceDocument,
        path: str,
) -> CommandResult:
    return CommandResult(
        command_id=command.command_id,
        status=CommandStatus.ACKNOWLEDGED,
        message=message,
        payload={
            "path": path,
            "workspace_name": document.name,
            "domain_count": len(document.domains),
            "topic_selection_count": len(document.topic_selections.selections),
            "plot_count": len(document.plots),
        },
        created_at=command.created_at,
    )


def _workspace_domains(
        selections: TopicSelectionState,
        subscriptions,
        plots: Tuple[WorkspacePlotDefinition, ...],
) -> Tuple[int, ...]:
    domains = {selection.domain_id for selection in selections.selections.values()}
    domains.update(request.domain_id for request in subscriptions)
    for plot in plots:
        domains.update(series.domain_id for series in plot.series)
    return tuple(sorted(domains))