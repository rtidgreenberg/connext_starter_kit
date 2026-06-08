"""Convert tab view models and command factories for rs_gui."""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from app_core import AppCommand


@dataclass(frozen=True)
class ConvertActionView:
    """Enabled/disabled state for one Convert tab action."""

    action_id: str
    label: str
    enabled: bool
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", bool(self.enabled))


@dataclass(frozen=True)
class ConvertStorageView:
    """Structured Converter input/output storage intent."""

    kind: str
    path: str
    storage_format: str = ""
    plugin_name: str = ""
    filename_expression: str = ""
    properties: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", str(self.kind))
        object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "storage_format", str(self.storage_format))
        object.__setattr__(self, "plugin_name", str(self.plugin_name))
        object.__setattr__(self, "filename_expression", str(self.filename_expression))
        object.__setattr__(self, "properties", dict(self.properties))

    def to_payload(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "storage_format": self.storage_format,
            "plugin_name": self.plugin_name,
            "filename_expression": self.filename_expression,
            "properties": dict(self.properties),
        }


@dataclass(frozen=True)
class ConvertPresetView:
    """Named Converter preset that maps to a future <converter> config."""

    preset_id: str
    label: str
    config_name: str
    output_format: str
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "preset_id", str(self.preset_id))
        object.__setattr__(self, "label", str(self.label))
        object.__setattr__(self, "config_name", str(self.config_name))
        object.__setattr__(self, "output_format", str(self.output_format))
        object.__setattr__(self, "description", str(self.description))


@dataclass(frozen=True)
class ConvertJobRow:
    """One immutable conversion execution snapshot."""

    job_id: str
    preset_id: str
    input_path: str
    output_path: str
    output_format: str
    state: str
    progress: str = ""
    created_at: str = ""
    message: str = ""

    # Phase 7: Result tracking fields
    started_at: str = ""
    completed_at: str = ""
    elapsed_seconds: int = 0
    record_count: int = 0
    result_summary: str = ""


@dataclass(frozen=True)
class ConvertLogRow:
    """One parsed Converter log row for a conversion job."""

    timestamp: str
    severity: str
    source: str
    job_id: str
    message: str


@dataclass(frozen=True)
class ConvertTabViewModel:
    """Immutable Convert-tab snapshot consumed by the GUI renderer."""

    config_file: str = ""
    selected_preset_id: str = ""
    selected_job_id: str = ""
    input_storage: ConvertStorageView = field(default_factory=lambda: ConvertStorageView("sqlite", ""))
    output_storage: ConvertStorageView = field(default_factory=lambda: ConvertStorageView("sqlite", ""))
    presets: Tuple[ConvertPresetView, ...] = field(default_factory=tuple)
    jobs: Tuple[ConvertJobRow, ...] = field(default_factory=tuple)
    logs: Tuple[ConvertLogRow, ...] = field(default_factory=tuple)
    actions: Tuple[ConvertActionView, ...] = field(default_factory=tuple)
    cli_preview: str = ""
    xml_preview: str = ""
    verbosity: str = "WARN"
    data_selection: str = "all"
    diagnostics: Tuple[str, ...] = field(default_factory=tuple)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "presets", tuple(self.presets))
        object.__setattr__(self, "jobs", tuple(self.jobs))
        object.__setattr__(self, "logs", tuple(self.logs))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "diagnostics", tuple(str(item) for item in self.diagnostics))
        object.__setattr__(self, "updated_at", float(self.updated_at))

    @property
    def selected_preset(self) -> Optional[ConvertPresetView]:
        for preset in self.presets:
            if preset.preset_id == self.selected_preset_id:
                return preset
        return None

    @property
    def selected_job(self) -> Optional[ConvertJobRow]:
        for job in self.jobs:
            if job.job_id == self.selected_job_id:
                return job
        return None

    @property
    def action_by_id(self) -> Mapping[str, ConvertActionView]:
        return {action.action_id: action for action in self.actions}


def build_convert_tab_view_model(
        presets: Iterable[ConvertPresetView] = (),
        jobs: Iterable[ConvertJobRow] = (),
        logs: Iterable[ConvertLogRow] = (),
        selected_preset_id: str = "",
        selected_job_id: str = "",
        input_storage: ConvertStorageView = None,
        output_storage: ConvertStorageView = None,
        config_file: str = "",
        verbosity: str = "WARN",
        data_selection: str = "all",
        diagnostics: Iterable[str] = (),
        now: float = None,
) -> ConvertTabViewModel:
    """Build a Convert-tab snapshot from structured Converter intent."""

    presets = tuple(presets)
    jobs = tuple(jobs)
    logs = tuple(logs)
    input_storage = input_storage or ConvertStorageView("sqlite", "")
    output_storage = output_storage or ConvertStorageView("sqlite", "")
    selected_preset_id = _selected_preset_id(presets, selected_preset_id)
    selected_job_id = _selected_job_id(jobs, selected_job_id)
    selected_preset = next((preset for preset in presets if preset.preset_id == selected_preset_id), None)
    selected_job = next((job for job in jobs if job.job_id == selected_job_id), None)
    diagnostics = tuple(str(item) for item in diagnostics) + _diagnostics(input_storage, output_storage, selected_preset)
    cli_preview = _cli_preview(config_file, selected_preset, input_storage, output_storage, verbosity)
    xml_preview = _xml_preview(selected_preset, input_storage, output_storage, data_selection)
    return ConvertTabViewModel(
        config_file=str(config_file),
        selected_preset_id=selected_preset_id,
        selected_job_id=selected_job_id,
        input_storage=input_storage,
        output_storage=output_storage,
        presets=presets,
        jobs=jobs,
        logs=logs,
        actions=_convert_actions(selected_preset, input_storage, output_storage, selected_job),
        cli_preview=cli_preview,
        xml_preview=xml_preview,
        verbosity=str(verbosity),
        data_selection=str(data_selection),
        diagnostics=diagnostics,
        updated_at=time.time() if now is None else float(now),
    )


def build_mock_convert_tab_view_model(now: float = 120.0) -> ConvertTabViewModel:
    """Return a deterministic Convert-tab snapshot for GUI smoke rendering."""

    presets = (
        ConvertPresetView(
            preset_id="sqlite_to_json",
            label="SQLite to JSON",
            config_name="sqlite_to_json",
            output_format="JSON_SQLITE",
            description="Export a Recording Service database into JSON-encoded SQLite",
        ),
        ConvertPresetView(
            preset_id="sqlite_to_cdr",
            label="SQLite to XCDR",
            config_name="sqlite_to_xcdr",
            output_format="XCDR_AUTO",
            description="Normalize a Recording Service database into XCDR storage",
        ),
    )
    input_storage = ConvertStorageView(
        kind="sqlite",
        path="services/recording_service_gui/log_dir/xcdr",
        storage_format="XCDR_AUTO",
    )
    output_storage = ConvertStorageView(
        kind="sqlite",
        path="services/converter_output/robot_run_03_json",
        storage_format="JSON_SQLITE",
        filename_expression="robot_run_03_json",
    )
    jobs = (
        ConvertJobRow(
            job_id="convert-robot-run-03",
            preset_id="sqlite_to_json",
            input_path=input_storage.path,
            output_path=output_storage.path,
            output_format="JSON_SQLITE",
            state="completed",
            progress="100%",
            created_at="13:18:04",
            message="Wrote JSON SQLite output",
        ),
    )
    logs = (
        ConvertLogRow("13:18:04", "INFO", "converter", "convert-robot-run-03", "Starting conversion"),
        ConvertLogRow("13:18:07", "INFO", "converter", "convert-robot-run-03", "Conversion finished"),
    )
    return build_convert_tab_view_model(
        presets=presets,
        jobs=jobs,
        logs=logs,
        selected_preset_id="sqlite_to_json",
        selected_job_id="convert-robot-run-03",
        input_storage=input_storage,
        output_storage=output_storage,
        config_file="services/converter_service_config.xml",
        verbosity="WARN:ERROR",
        data_selection="topics: RobotTelemetry, CameraStatus",
        now=now,
    )


def build_convert_action_command(action_id: str, convert: ConvertTabViewModel) -> AppCommand:
    """Translate a Convert-tab button action into an app-core command intent."""

    action_to_command = {
        "run": "convert.run",
        "cancel": "convert.cancel",
        "open_output": "convert.open_output",
        "inspect_output": "convert.inspect_output",
    }
    if action_id not in action_to_command:
        raise ValueError(f"Unsupported Convert tab action: {action_id}")
    payload = _command_payload(convert)
    return AppCommand(
        command_type=action_to_command[action_id],
        target=str(payload.get("job_id") or convert.output_storage.path),
        payload=payload,
    )


def _command_payload(convert: ConvertTabViewModel) -> Dict[str, Any]:
    preset = convert.selected_preset
    job = convert.selected_job
    return {
        "job_id": job.job_id if job is not None else "",
        "config_file": convert.config_file,
        "config_name": preset.config_name if preset is not None else "",
        "preset_id": preset.preset_id if preset is not None else "",
        "input_storage": convert.input_storage.to_payload(),
        "output_storage": convert.output_storage.to_payload(),
        "output_format": preset.output_format if preset is not None else convert.output_storage.storage_format,
        "verbosity": convert.verbosity,
        "data_selection": convert.data_selection,
        "cli_preview": convert.cli_preview,
        "xml_preview": convert.xml_preview,
    }


def _selected_preset_id(presets: Tuple[ConvertPresetView, ...], requested: str) -> str:
    if requested and any(preset.preset_id == requested for preset in presets):
        return str(requested)
    if presets:
        return presets[0].preset_id
    return str(requested)


def _selected_job_id(jobs: Tuple[ConvertJobRow, ...], requested: str) -> str:
    if requested and any(job.job_id == requested for job in jobs):
        return str(requested)
    if jobs:
        return jobs[0].job_id
    return str(requested)


def _convert_actions(
        selected_preset: Optional[ConvertPresetView],
        input_storage: ConvertStorageView,
        output_storage: ConvertStorageView,
        selected_job: Optional[ConvertJobRow],
) -> Tuple[ConvertActionView, ...]:
    ready = selected_preset is not None and bool(input_storage.path.strip()) and bool(output_storage.path.strip())
    active = selected_job is not None and selected_job.state in ("queued", "starting", "running")
    completed = selected_job is not None and selected_job.state == "completed"
    disabled_reason = _disabled_reason(selected_preset, input_storage, output_storage)
    return (
        ConvertActionView("run", "Run Conversion", ready, disabled_reason),
        ConvertActionView("cancel", "Cancel", active, "no active conversion" if not active else ""),
        ConvertActionView("open_output", "Open Output", completed, "no completed output" if not completed else ""),
        ConvertActionView("inspect_output", "Inspect Output", completed, "no completed output" if not completed else ""),
    )


def _disabled_reason(
        selected_preset: Optional[ConvertPresetView],
        input_storage: ConvertStorageView,
        output_storage: ConvertStorageView,
) -> str:
    if selected_preset is None:
        return "converter preset required"
    if not input_storage.path.strip():
        return "input storage path required"
    if not output_storage.path.strip():
        return "output storage path required"
    return ""


def _diagnostics(
        input_storage: ConvertStorageView,
        output_storage: ConvertStorageView,
        selected_preset: Optional[ConvertPresetView],
) -> Tuple[str, ...]:
    diagnostics = []
    if selected_preset is None:
        diagnostics.append("No Converter preset selected")
    if not input_storage.path.strip():
        diagnostics.append("No input storage path selected")
    if not output_storage.path.strip():
        diagnostics.append("No output storage path selected")
    return tuple(diagnostics)


def _cli_preview(
        config_file: str,
        preset: Optional[ConvertPresetView],
        input_storage: ConvertStorageView,
        output_storage: ConvertStorageView,
        verbosity: str,
) -> str:
    config_name = preset.config_name if preset is not None else ""
    return " ".join(part for part in (
        "rticonverter",
        f"-cfgFile {config_file}" if config_file else "",
        f"-cfgName {config_name}" if config_name else "",
        f"-verbosity {verbosity}" if verbosity else "",
        f"-Dinput.path={input_storage.path}" if input_storage.path else "",
        f"-Doutput.path={output_storage.path}" if output_storage.path else "",
    ) if part)


def _xml_preview(
        preset: Optional[ConvertPresetView],
        input_storage: ConvertStorageView,
        output_storage: ConvertStorageView,
        data_selection: str,
) -> str:
    config_name = preset.config_name if preset is not None else "converter"
    output_format = preset.output_format if preset is not None else output_storage.storage_format
    return "\n".join((
        "<dds>",
        f"  <converter name=\"{config_name}\">",
        "    <input_storage>",
        f"      <sqlite><database_dir>{input_storage.path}</database_dir></sqlite>",
        "    </input_storage>",
        "    <output_storage>",
        f"      <sqlite><database_dir>{output_storage.path}</database_dir></sqlite>",
        f"      <storage_format>{output_format}</storage_format>",
        "    </output_storage>",
        f"    <data_selection>{data_selection}</data_selection>",
        "  </converter>",
        "</dds>",
    ))
