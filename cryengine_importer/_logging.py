"""Logging helpers for the CryEngine importer.

The package is otherwise free of any ``logging`` configuration so that
it stays embeddable; this module only adds *opt-in* sinks. The Blender
operator wraps each import in :func:`attach_for_operator`, which:

* installs a :class:`BpyReportHandler` that mirrors WARNING+ messages
  to ``operator.report`` (so they appear in Blender's Info editor /
  status bar);
* installs a stderr :class:`logging.StreamHandler` so DEBUG/INFO is
  visible in Blender's System Console;
* bumps the package logger to DEBUG when the user ticks "Verbose
  Logging" in the import dialog, otherwise leaves it at INFO.

When the importer is used outside Blender (tests, the headless smoke
script) the same helper works because :class:`BpyReportHandler` is
optional — pass ``operator=None`` to get stderr only.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import Iterator

PACKAGE_LOGGER_NAME = "cryengine_importer"

_DEFAULT_FORMAT = "%(levelname)s %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Return a logger scoped under the package logger."""
    return logging.getLogger(name)


class BpyReportHandler(logging.Handler):
    """Forward WARNING/ERROR records to ``Operator.report``.

    DEBUG/INFO records are dropped (they go to the sibling stderr
    handler instead — surfacing every INFO line as a Blender popup
    would be too noisy).
    """

    _LEVEL_MAP = {
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "ERROR",
    }

    def __init__(self, operator) -> None:  # type: ignore[no-untyped-def]
        super().__init__(level=logging.WARNING)
        self._operator = operator

    def emit(self, record: logging.LogRecord) -> None:
        try:
            kind = self._LEVEL_MAP.get(record.levelno)
            if kind is None:
                return
            msg = self.format(record)
            self._operator.report({kind}, msg)
        except Exception:  # pragma: no cover - never let logging crash callers
            pass


@contextlib.contextmanager
def attach_for_operator(
    operator,  # type: ignore[no-untyped-def]
    *,
    verbose: bool,
) -> Iterator[None]:
    """Configure package logging for the duration of one import.

    On entry: attaches a stderr handler (always) and a
    :class:`BpyReportHandler` (when ``operator`` is not None), and
    raises the ``cryengine_importer`` logger to DEBUG if ``verbose``
    else INFO. On exit: restores the previous level and removes both
    handlers.
    """
    pkg_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    previous_level = pkg_logger.level
    previous_propagate = pkg_logger.propagate

    formatter = logging.Formatter(_DEFAULT_FORMAT)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(formatter)
    pkg_logger.addHandler(stream_handler)

    bpy_handler: BpyReportHandler | None = None
    if operator is not None:
        bpy_handler = BpyReportHandler(operator)
        bpy_handler.setFormatter(formatter)
        pkg_logger.addHandler(bpy_handler)

    pkg_logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    # We add our own handlers, so don't double-emit through the root
    # logger (which Blender may have wired to its own console).
    pkg_logger.propagate = False

    try:
        yield
    finally:
        pkg_logger.removeHandler(stream_handler)
        if bpy_handler is not None:
            pkg_logger.removeHandler(bpy_handler)
        pkg_logger.setLevel(previous_level)
        pkg_logger.propagate = previous_propagate


__all__ = [
    "PACKAGE_LOGGER_NAME",
    "BpyReportHandler",
    "attach_for_operator",
    "get_logger",
]
