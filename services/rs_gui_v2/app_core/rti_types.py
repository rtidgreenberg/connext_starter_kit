"""RTI Connext XML DynamicData type registry for rs_gui_v2.

This module owns Connext `QosProvider.type()` lookups. The DDS-free type catalog
and resolution DTOs remain in `types.py`.
"""

from dataclasses import dataclass
import glob
import os
from typing import Any, Dict, Iterable, Optional, Tuple

from .connext_environment import (
    detect_nddshome,
    ensure_rti_license,
    validate_generated_types,
)
from .types import (
    TypeAvailabilityStatus,
    TypeCatalog,
    TypeResolution,
    catalog_from_xml_files,
)


@dataclass(frozen=True)
class RtiTypeRegistryConfig:
    """Filesystem inputs for the RTI XML DynamicData type registry."""

    xml_types_dir: str
    xml_files: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DynamicTypeLookup:
    """Result of resolving a local catalog entry to a Connext DynamicType."""

    resolution: TypeResolution
    dynamic_type: Any = None

    @property
    def available(self) -> bool:
        return self.resolution.available and self.dynamic_type is not None


class RtiTypeRegistry:
    """Load v2-owned XML type files and resolve Connext DynamicTypes by name."""

    def __init__(
            self,
            config: Optional[RtiTypeRegistryConfig] = None,
            dds_module: Any = None,
    ) -> None:
        self.config = config or default_rti_type_registry_config()
        self._dds = dds_module
        self._uses_real_connext = dds_module is None
        self._catalog: Optional[TypeCatalog] = None
        self._providers: Dict[str, Any] = {}

    def catalog(self) -> TypeCatalog:
        if self._catalog is None:
            self._prepare_runtime_environment()
            self._catalog = catalog_from_xml_files(self._xml_paths())
        return self._catalog

    def resolve(self, type_name: str) -> TypeResolution:
        return self.catalog().resolve(type_name)

    def lookup(self, type_name: str) -> DynamicTypeLookup:
        resolution = self.resolve(type_name)
        if not resolution.available:
            return DynamicTypeLookup(resolution=resolution)

        source = self.catalog().source_for(resolution.resolved_type_name)
        if source is None:
            return DynamicTypeLookup(resolution=TypeResolution(
                type_name=type_name,
                status=TypeAvailabilityStatus.MISSING,
                message="type source was not found in the local catalog",
            ))

        provider = self._provider_for_source(source.source)
        try:
            dynamic_type = provider.type(resolution.resolved_type_name)
        except Exception as exc:
            return DynamicTypeLookup(resolution=TypeResolution(
                type_name=type_name,
                status=TypeAvailabilityStatus.MISSING,
                source=source.source,
                kind=source.kind,
                candidates=resolution.candidates,
                message=f"Connext failed to load DynamicType: {exc}",
            ))
        return DynamicTypeLookup(resolution=resolution, dynamic_type=dynamic_type)

    def dynamic_type(self, type_name: str) -> Any:
        lookup = self.lookup(type_name)
        if lookup.available:
            return lookup.dynamic_type
        raise KeyError(lookup.resolution.message or f"DynamicType not available: {type_name}")

    def _provider_for_source(self, source: str) -> Any:
        source = os.path.abspath(source)
        provider = self._providers.get(source)
        if provider is not None:
            return provider
        self._load_connext_module()
        provider = self._dds.QosProvider(source)
        self._providers[source] = provider
        return provider

    def _xml_paths(self) -> Tuple[str, ...]:
        if self.config.xml_files:
            paths = tuple(
                path if os.path.isabs(path) else os.path.join(self.config.xml_types_dir, path)
                for path in self.config.xml_files
            )
        else:
            paths = tuple(sorted(glob.glob(os.path.join(self.config.xml_types_dir, "*.xml"))))
        missing = tuple(path for path in paths if not os.path.isfile(path))
        if missing:
            raise FileNotFoundError("Required XML type file not found: " + missing[0])
        return tuple(os.path.abspath(path) for path in paths)

    def _load_connext_module(self) -> None:
        if self._dds is None:
            import rti.connextdds as dds
            self._dds = dds

    def _prepare_runtime_environment(self) -> None:
        if not self._uses_real_connext:
            return
        nddshome = detect_nddshome()
        ensure_rti_license(nddshome)
        validate_generated_types(self.config.xml_types_dir, nddshome)


def default_rti_type_registry_config() -> RtiTypeRegistryConfig:
    root_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    return RtiTypeRegistryConfig(xml_types_dir=os.path.join(root_dir, "xml_types"))