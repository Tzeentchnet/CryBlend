"""Tests for the ArcheAge ``.cal`` animation list loader."""

from __future__ import annotations

import io
from typing import BinaryIO

from cryengine_importer.core.cal_loader import (
    load_cal_with_includes,
    parse_cal,
)


# -- in-memory fake pack-FS ----------------------------------------------


class _FakeFS:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = {k.replace("\\", "/").lower(): v for k, v in files.items()}

    def exists(self, path: str) -> bool:
        return path.replace("\\", "/").lower() in self._files

    def open(self, path: str) -> BinaryIO:
        data = self._files[path.replace("\\", "/").lower()].encode("utf-8")
        return io.BytesIO(data)


# -- parse_cal -----------------------------------------------------------


def test_parse_cal_extracts_filepath_and_animations() -> None:
    text = """
        // header comment
        #filepath = animations/character/human

        idle = idle.caf
        walk = locomotion/walk.caf  // inline comment
        run  =  locomotion/run.caf

        $Include = base.cal
        $UnknownDirective = ignored
        _NORMAL_WALK = ignored_locomotion
        -- old-style comment
    """
    cal = parse_cal(text)
    assert cal.file_path == "animations/character/human"
    assert cal.animations == {
        "idle": "idle.caf",
        "walk": "locomotion/walk.caf",
        "run": "locomotion/run.caf",
    }
    assert cal.includes == ["base.cal"]


def test_parse_cal_ignores_blank_and_malformed_lines() -> None:
    cal = parse_cal("\n\n   \nno_equals_here\nfoo = bar\n")
    assert cal.animations == {"foo": "bar"}


# -- load_cal_with_includes ----------------------------------------------


def test_load_cal_with_includes_merges_child_animations() -> None:
    fs = _FakeFS({
        "characters/human.cal": (
            "#filepath = animations/human\n"
            "idle = idle.caf\n"
            "$Include = base.cal\n"
        ),
        "characters/base.cal": (
            "walk = walk.caf\n"
            "idle = OVERRIDDEN.caf\n"  # parent must win
        ),
    })
    cal = load_cal_with_includes("characters/human.cal", fs)
    assert cal.file_path == "animations/human"
    assert cal.animations["idle"] == "idle.caf"  # parent wins
    assert cal.animations["walk"] == "walk.caf"


def test_load_cal_with_includes_handles_cycles() -> None:
    fs = _FakeFS({
        "a.cal": "$Include = b.cal\nfoo = a.caf\n",
        "b.cal": "$Include = a.cal\nbar = b.caf\n",
    })
    cal = load_cal_with_includes("a.cal", fs)
    assert cal.animations == {"foo": "a.caf", "bar": "b.caf"}


def test_load_cal_with_includes_inherits_filepath_from_child() -> None:
    fs = _FakeFS({
        "main.cal": "$Include = sub.cal\nidle = idle.caf\n",
        "sub.cal": "#filepath = animations/from_child\nwalk = walk.caf\n",
    })
    cal = load_cal_with_includes("main.cal", fs)
    assert cal.file_path == "animations/from_child"


def test_load_cal_with_includes_resolves_against_game_prefix() -> None:
    fs = _FakeFS({
        "characters/main.cal": "$Include = shared/base.cal\nidle = idle.caf\n",
        "game/shared/base.cal": "walk = walk.caf\n",
    })
    cal = load_cal_with_includes("characters/main.cal", fs)
    assert cal.animations == {"idle": "idle.caf", "walk": "walk.caf"}
