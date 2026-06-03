"""Shared DPG rendering utilities for rs_gui_v2 tabs."""

from contextlib import nullcontext
from typing import Optional


PRIMARY_BUTTON_WIDTH = 220
ACTION_BUTTON_WIDTH = 170
COMPACT_BUTTON_WIDTH = 90
DOMAIN_ID_INPUT_WIDTH = 72
STORAGE_PATH_INPUT_WIDTH = 640


def add_action_button(
        dpg,
        label: str,
        callback=None,
        enabled: bool = True,
        width: int = ACTION_BUTTON_WIDTH,
):
    kwargs = {"label": label, "enabled": enabled, "width": int(width)}
    if callback is not None:
        kwargs["callback"] = callback
    return dpg.add_button(**kwargs)


def add_labeled_input_text(
        dpg,
        visible_label: str,
        input_label: str,
        default_value: str = "",
        tag: Optional[str] = None,
        callback=None,
        width: Optional[int] = None,
        readonly: bool = False,
):
    dpg.add_text(visible_label)
    kwargs = {
        "label": input_label,
        "default_value": default_value,
    }
    if width is not None:
        kwargs["width"] = int(width)
    if readonly:
        kwargs["readonly"] = True
    if tag is not None:
        kwargs["tag"] = tag
    if callback is not None:
        kwargs["callback"] = callback
    return dpg.add_input_text(**kwargs)


def add_labeled_checkbox(
        dpg,
        visible_label: str,
        default_value: bool = False,
        tag: Optional[str] = None,
        callback=None,
):
    dpg.add_text(visible_label)
    kwargs = {"default_value": bool(default_value)}
    if tag is not None:
        kwargs["tag"] = tag
    if callback is not None:
        kwargs["callback"] = callback
    return dpg.add_checkbox(**kwargs)


def collapsible_section(dpg, label: str, default_open: bool = False):
    builder = getattr(dpg, "collapsing_header", None)
    if callable(builder):
        try:
            return builder(label=label, default_open=default_open)
        except TypeError:
            return builder(label=label)
    group_builder = getattr(dpg, "group", None)
    if callable(group_builder):
        return group_builder()
    return nullcontext()


def apply_button_theme_if_supported(dpg) -> None:
    required = (
        "theme",
        "theme_component",
        "add_theme_style",
        "add_theme_color",
        "bind_theme",
        "mvButton",
        "mvThemeCat_Core",
        "mvStyleVar_FramePadding",
        "mvStyleVar_FrameRounding",
        "mvThemeCol_Button",
        "mvThemeCol_ButtonHovered",
        "mvThemeCol_ButtonActive",
    )
    if any(not hasattr(dpg, name) for name in required):
        return
    try:
        with dpg.theme(tag="rs_gui_v2_accessible_theme"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 14, 8, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6, category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_Button, (36, 99, 168, 255), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (56, 122, 193, 255), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (24, 77, 136, 255), category=dpg.mvThemeCat_Core)
        dpg.bind_theme("rs_gui_v2_accessible_theme")
    except Exception:
        return


def dpg_text_value(dpg, tag: str, default: str = "") -> str:
    try:
        value = dpg.get_value(tag)
    except Exception:
        return str(default)
    if value is None:
        return str(default)
    return str(value)


def int_text_value(dpg, tag: str, default: int = 0) -> int:
    value = dpg_text_value(dpg, tag, str(default)).strip()
    return int(value or default)


def float_text_value(dpg, tag: str, default: float = 0.0) -> float:
    value = dpg_text_value(dpg, tag, str(default)).strip()
    return float(value or default)


def has_item(dpg, tag: str) -> bool:
    does_item_exist = getattr(dpg, "does_item_exist", None)
    if callable(does_item_exist):
        try:
            return bool(does_item_exist(tag))
        except Exception:
            return False
    return False


def widget_value(dpg, tag: str, default: str) -> str:
    get_value = getattr(dpg, "get_value", None)
    if get_value is None:
        return default
    value = get_value(tag)
    return str(value if value is not None else default)
