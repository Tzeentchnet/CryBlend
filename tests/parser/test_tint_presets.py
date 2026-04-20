"""Phase 11 — tint preset save/load round-trip + edge cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cryengine_importer.materials.tint_presets import (
    SCHEMA_VERSION,
    TintPresetError,
    default_preset_path,
    load_preset,
    save_preset,
)


def test_round_trip_preserves_keys_and_values(tmp_path: Path) -> None:
    src = {
        "DiffuseTint1": (0.5, 0.25, 0.125),
        "DirtColor": (0.13, 0.10, 0.08),
    }
    p = tmp_path / "preset.json"
    save_preset(p, src, material_name="Anodized_01_A")

    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["schema"] == SCHEMA_VERSION
    assert payload["material"] == "Anodized_01_A"

    loaded = load_preset(p)
    assert set(loaded) == set(src)
    for k, v in src.items():
        assert loaded[k] == pytest.approx(v)


def test_save_preset_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "preset.json"
    save_preset(p, {"DiffuseTint1": (1.0, 0.0, 0.0)})
    save_preset(p, {"DiffuseTint1": (0.0, 1.0, 0.0)})
    assert load_preset(p)["DiffuseTint1"] == pytest.approx((0.0, 1.0, 0.0))


def test_load_preset_accepts_loose_form(tmp_path: Path) -> None:
    """Old-style preset with no `schema`/`tints` envelope still loads."""
    p = tmp_path / "loose.json"
    p.write_text(json.dumps({"DiffuseTint1": [0.1, 0.2, 0.3]}), encoding="utf-8")
    loaded = load_preset(p)
    assert loaded["DiffuseTint1"] == pytest.approx((0.1, 0.2, 0.3))


def test_load_preset_rejects_non_triple(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"tints": {"X": [1.0, 2.0]}}), encoding="utf-8")
    with pytest.raises(TintPresetError):
        load_preset(p)


def test_load_preset_rejects_non_numeric(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps({"tints": {"X": ["a", "b", "c"]}}), encoding="utf-8"
    )
    with pytest.raises(TintPresetError):
        load_preset(p)


def test_load_preset_rejects_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(TintPresetError):
        load_preset(p)


def test_load_preset_rejects_non_object(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(TintPresetError):
        load_preset(p)


def test_default_preset_path_strips_unsafe_chars(tmp_path: Path) -> None:
    mtl = tmp_path / "hero.mtl"
    out = default_preset_path(mtl, "Anodized 01/A")
    assert out.parent == mtl.parent
    # Slash + space replaced with underscores.
    assert out.name == "hero.Anodized_01_A.tint.json"
