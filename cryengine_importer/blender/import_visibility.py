"""Default visibility rules for imported Blender objects."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


DEFAULT_HIDDEN_PROP = "cryblend_default_hidden"
_DEFAULT_HIDDEN_NAME_MARKERS = ("_destroyed", "_collision", "occlusion")
_DEFAULT_HIDDEN_NAME_PREFIXES = ("physics_",)


def should_hide_imported_object_name(name: str | None) -> bool:
    """Return True when an imported object name should start hidden."""
    lowered = (name or "").lower()
    if lowered.startswith(_DEFAULT_HIDDEN_NAME_PREFIXES):
        return True
    return any(marker in lowered for marker in _DEFAULT_HIDDEN_NAME_MARKERS)


def is_default_hidden_object(obj: Any) -> bool:
    """Return True if ``obj`` matches or was marked by the default rule."""
    try:
        if bool(obj.get(DEFAULT_HIDDEN_PROP, False)):
            return True
    except AttributeError:
        pass
    return should_hide_imported_object_name(getattr(obj, "name", None))


def apply_import_visibility_defaults(objects: Iterable[Any]) -> None:
    """Hide imported objects whose names match default-hidden markers."""
    for obj in objects:
        if is_default_hidden_object(obj):
            set_imported_object_visibility(obj, True)


def set_imported_object_visibility(obj: Any, visible: bool) -> None:
    """Set visibility while preserving default-hidden name rules."""
    default_hidden = is_default_hidden_object(obj)
    if default_hidden:
        try:
            obj[DEFAULT_HIDDEN_PROP] = True
        except TypeError:
            pass
    hidden = (not visible) or default_hidden
    obj.hide_viewport = hidden
    obj.hide_render = hidden


__all__ = [
    "DEFAULT_HIDDEN_PROP",
    "apply_import_visibility_defaults",
    "is_default_hidden_object",
    "set_imported_object_visibility",
    "should_hide_imported_object_name",
]