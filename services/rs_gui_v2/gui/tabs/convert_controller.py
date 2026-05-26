"""Convert tab controller for fake-first GUI command routing with live service support."""

from dataclasses import dataclass, replace
import time
from typing import Iterable, Mapping, Optional, Tuple

from app_core import AppCommand, CommandResult, CommandStatus
from app_core.services import ServiceInstanceRef

from .convert_tab import (
    ConvertJobRow,
    ConvertPresetView,
    ConvertStorageView,
    ConvertTabViewModel,
    build_convert_tab_view_model,
    build_mock_convert_tab_view_model,
)
from .convert_service_facade import ConverterServiceFacade


@dataclass(frozen=True)
class ConvertTabControllerConfig:
    """Runtime wiring options for the Convert tab controller."""

    config_file: str = ""
    selected_preset_id: str = ""
    selected_job_id: str = ""
    input_storage_path: str = ""
    output_storage_path: str = ""
    data_selection: str = "all"
    verbosity: str = "WARN"
    service: Optional[ServiceInstanceRef] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_file", str(self.config_file))
        object.__setattr__(self, "selected_preset_id", str(self.selected_preset_id))
        object.__setattr__(self, "selected_job_id", str(self.selected_job_id))
        object.__setattr__(self, "input_storage_path", str(self.input_storage_path))
        object.__setattr__(self, "output_storage_path", str(self.output_storage_path))
        object.__setattr__(self, "data_selection", str(self.data_selection))
        object.__setattr__(self, "verbosity", str(self.verbosity))


class ConvertTabController:
    """Build Convert tab snapshots and apply queued Convert commands (fake or live)."""

    def __init__(
            self,
            presets: Iterable[ConvertPresetView] = (),
            diagnostics: Iterable[str] = (),
            service_facade: Optional[ConverterServiceFacade] = None,
            config: ConvertTabControllerConfig = None,
            clock=time.time,
    ) -> None:
        self._presets = tuple(presets)
        self._jobs = ()
        self._diagnostics = tuple(str(item) for item in diagnostics)
        self._service_facade = service_facade
        self._config = config or ConvertTabControllerConfig()
        self._clock = clock
        self._last_view = ConvertTabViewModel()
        self._service_ready = False

    @classmethod
    def mock(cls, clock=time.time) -> "ConvertTabController":
        """Create a controller seeded with the deterministic mock Convert view."""

        view = build_mock_convert_tab_view_model()
        config = ConvertTabControllerConfig(
            config_file=view.config_file,
            selected_preset_id=view.selected_preset_id,
            selected_job_id=view.selected_job_id,
            input_storage_path=view.input_storage.path,
            output_storage_path=view.output_storage.path,
            data_selection=view.data_selection,
            verbosity=view.verbosity,
        )
        controller = cls(
            presets=view.presets,
            config=config,
            clock=clock,
        )
        # Populate _jobs from mock view so controller state matches the seeded view
        controller._jobs = view.jobs
        controller._last_view = view
        return controller

    @classmethod
    def from_service(
            cls,
            service: ServiceInstanceRef,
            presets: Iterable[ConvertPresetView] = (),
            service_facade: Optional[ConverterServiceFacade] = None,
            config: ConvertTabControllerConfig = None,
            clock=time.time,
    ) -> "ConvertTabController":
        """Create a controller wired to a live Converter Service instance."""
        cfg = config or ConvertTabControllerConfig()
        cfg = replace(cfg, service=service)
        return cls(
            presets=presets,
            service_facade=service_facade,
            config=cfg,
            clock=clock,
        )

    @property
    def selected_preset_id(self) -> str:
        return self._config.selected_preset_id

    @property
    def last_view(self) -> ConvertTabViewModel:
        return self._last_view

    def select_preset(self, preset_id: str) -> ConvertPresetView:
        """Select a Converter preset by preset id."""

        preset = self._preset_by_id(str(preset_id))
        self._config = replace(self._config, selected_preset_id=preset.preset_id)
        return preset

    def handle_command(self, command: AppCommand) -> CommandResult:
        """Apply a queued Convert command to the controller state."""

        payload = dict(command.payload)
        if command.command_type == "convert.run":
            return self._handle_run_conversion(command, payload)
        if command.command_type == "convert.cancel":
            return self._handle_cancel_conversion(command, payload)
        if command.command_type == "convert.open_output":
            return self._handle_open_output(command, payload)
        if command.command_type == "convert.inspect_output":
            return self._handle_inspect_output(command, payload)
        raise ValueError(f"Unsupported Convert command type: {command.command_type}")

    async def refresh_view(self) -> ConvertTabViewModel:
        """Return the next Convert-tab view from controller state (with live service sync)."""

        # Update service ready status if facade is available
        if self._service_facade:
            self._service_ready = await self._service_facade.is_service_ready()

        input_storage = ConvertStorageView("sqlite", self._config.input_storage_path, "XCDR_AUTO")
        output_storage = ConvertStorageView("sqlite", self._config.output_storage_path, "JSON_SQLITE")
        view = build_convert_tab_view_model(
            presets=self._presets,
            jobs=self._jobs,
            logs=(),
            selected_preset_id=self._config.selected_preset_id,
            selected_job_id=self._config.selected_job_id,
            input_storage=input_storage,
            output_storage=output_storage,
            config_file=self._config.config_file,
            verbosity=self._config.verbosity,
            data_selection=self._config.data_selection,
            diagnostics=self._get_diagnostics(),
        )
        if view.selected_preset_id != self._config.selected_preset_id:
            self._config = replace(self._config, selected_preset_id=view.selected_preset_id)
        self._last_view = view
        return view

    def _handle_run_conversion(
            self,
            command: AppCommand,
            payload: Mapping[str, object],
    ) -> CommandResult:
        """Process a convert.run command and create a new job snapshot."""

        config_name = str(payload.get("config_name", self._config.selected_preset_id))
        if not config_name:
            raise ValueError("convert.run requires a preset config_name")
        input_path = str(payload.get("input_storage", {}).get("path", self._config.input_storage_path))
        if not input_path.strip():
            raise ValueError("convert.run requires an input storage path")
        output_path = str(payload.get("output_storage", {}).get("path", self._config.output_storage_path))
        if not output_path.strip():
            raise ValueError("convert.run requires an output storage path")
        output_format = str(payload.get("output_format", "JSON_SQLITE"))
        job_id = f"convert-{int(self._clock())}"
        job = ConvertJobRow(
            job_id=job_id,
            preset_id=config_name,
            input_path=input_path,
            output_path=output_path,
            output_format=output_format,
            state="queued",
            progress="0%",
            created_at=_timestamp(self._clock()),
            message="Conversion queued",
        )
        self._jobs = tuple(list(self._jobs) + [job])
        self._config = replace(self._config, selected_job_id=job_id)
        return _command_result(command, f"Queued conversion job {job_id}", job)

    def _handle_cancel_conversion(
            self,
            command: AppCommand,
            payload: Mapping[str, object],
    ) -> CommandResult:
        """Process a convert.cancel command and update the selected job state."""

        job_id = str(payload.get("job_id", self._config.selected_job_id))
        if not job_id:
            raise ValueError("convert.cancel requires a job_id")
        job = self._job_by_id(job_id)
        if job.state not in ("queued", "starting", "running"):
            raise ValueError(f"Cannot cancel job in state {job.state}")
        updated_job = replace(job, state="cancel_requested", message="Cancellation requested")
        self._jobs = tuple(
            updated_job if j.job_id == job_id else j for j in self._jobs
        )
        return _command_result(command, f"Requested cancellation of job {job_id}", updated_job)

    def _handle_open_output(
            self,
            command: AppCommand,
            payload: Mapping[str, object],
    ) -> CommandResult:
        """Process a convert.open_output command (no state change, intent only)."""

        job_id = str(payload.get("job_id", self._config.selected_job_id))
        if not job_id:
            raise ValueError("convert.open_output requires a job_id")
        job = self._job_by_id(job_id)
        if job.state != "completed":
            raise ValueError(f"Cannot open output for job in state {job.state}")
        return CommandResult(
            command_id=command.command_id,
            status=CommandStatus.ACKNOWLEDGED,
            message=f"Opening output directory for job {job_id}",
            payload={
                "job_id": job.job_id,
                "output_path": job.output_path,
                "state": job.state,
            },
            created_at=command.created_at,
        )

    def _handle_inspect_output(
            self,
            command: AppCommand,
            payload: Mapping[str, object],
    ) -> CommandResult:
        """Process a convert.inspect_output command (no state change, intent only)."""

        job_id = str(payload.get("job_id", self._config.selected_job_id))
        if not job_id:
            raise ValueError("convert.inspect_output requires a job_id")
        job = self._job_by_id(job_id)
        if job.state != "completed":
            raise ValueError(f"Cannot inspect output for job in state {job.state}")
        return CommandResult(
            command_id=command.command_id,
            status=CommandStatus.ACKNOWLEDGED,
            message=f"Inspecting output for job {job_id}",
            payload={
                "job_id": job.job_id,
                "output_format": job.output_format,
                "state": job.state,
            },
            created_at=command.created_at,
        )

    def _preset_by_id(self, preset_id: str) -> ConvertPresetView:
        for preset in self._presets:
            if preset.preset_id == preset_id or preset.config_name == preset_id:
                return preset
        raise ValueError(f"Unknown Convert preset: {preset_id}")

    def _job_by_id(self, job_id: str) -> ConvertJobRow:
        for job in self._jobs:
            if job.job_id == job_id:
                return job
        raise ValueError(f"Unknown Convert job: {job_id}")

    def _get_diagnostics(self) -> Tuple[str, ...]:
        """Build diagnostic messages including service status."""
        msgs = list(self._diagnostics)
        if self._service_facade:
            if self._service_ready:
                msgs.append("✓ Converter Service connected and ready")
            else:
                msgs.append("⚠ Converter Service not ready (using local mode)")
        else:
            msgs.append("ℹ Mock mode (no Converter Service facade)")
        return tuple(msgs)

    @property
    def is_service_available(self) -> bool:
        return self._service_facade is not None and self._service_ready

    def workspace_config(self) -> Mapping[str, object]:
        """Export Convert controller state for workspace persistence."""
        return {
            "config_file": self._config.config_file,
            "selected_preset_id": self._config.selected_preset_id,
            "selected_job_id": self._config.selected_job_id,
            "input_storage_path": self._config.input_storage_path,
            "output_storage_path": self._config.output_storage_path,
            "data_selection": self._config.data_selection,
            "verbosity": self._config.verbosity,
        }

    def workspace_metadata(self) -> Mapping[str, object]:
        """Export Convert metadata for workspace diagnostics."""
        return {
            "job_count": len(self._jobs),
            "preset_count": len(self._presets),
            "selected_preset": self._config.selected_preset_id,
            "service_available": self.is_service_available,
        }

    def apply_workspace_intent(self, metadata: Mapping[str, object]) -> None:
        """Restore Convert controller state from workspace metadata."""
        config_dict = dict(metadata)
        self._config = replace(
            self._config,
            config_file=str(config_dict.get("config_file", self._config.config_file)),
            selected_preset_id=str(config_dict.get("selected_preset_id", self._config.selected_preset_id)),
            selected_job_id=str(config_dict.get("selected_job_id", self._config.selected_job_id)),
            input_storage_path=str(config_dict.get("input_storage_path", self._config.input_storage_path)),
            output_storage_path=str(config_dict.get("output_storage_path", self._config.output_storage_path)),
            data_selection=str(config_dict.get("data_selection", self._config.data_selection)),
            verbosity=str(config_dict.get("verbosity", self._config.verbosity)),
        )


def _command_result(
        command: AppCommand,
        message: str,
        job: ConvertJobRow,
) -> CommandResult:
    return CommandResult(
        command_id=command.command_id,
        status=CommandStatus.ACKNOWLEDGED,
        message=message,
        payload={
            "job_id": job.job_id,
            "preset_id": job.preset_id,
            "state": job.state,
            "progress": job.progress,
        },
        created_at=command.created_at,
    )


def _timestamp(value: float) -> str:
    """Format current time as HH:MM:SS."""
    seconds = int(value) % 86400
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    sec = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"
