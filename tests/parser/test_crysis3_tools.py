from __future__ import annotations

from cryengine_importer.blender.crysis2_tools import CRYSIS1, CRYSIS3
from cryengine_importer.blender.crysis3_tools import (
    audit_crytools_asset,
    audit_crysis3_asset,
    apply_crysis3_settings,
    format_attachment_xml,
    format_crytools_audit_report,
    format_crysis3_audit_report,
    metadata_to_udp_lines,
    metadata_value_matches,
    parse_metadata_text,
    serialize_metadata,
)


def test_parse_metadata_text_accepts_json_and_legacy_udp_lines() -> None:
    assert parse_metadata_text('{"Mass": 10, "box": true}') == {
        "mass": 10,
        "box": True,
    }
    assert parse_metadata_text("mass = 12\nbox\nrotaxes = xy") == {
        "mass": 12.0,
        "box": True,
        "rotaxes": "xy",
    }


def test_apply_crysis3_settings_replaces_mutually_exclusive_tags() -> None:
    out = apply_crysis3_settings(
        "density = 4\nsphere\nlimit = 7",
        {
            "use_mass": True,
            "mass": 10,
            "use_density": False,
            "primitive": "BOX",
            "use_joint": True,
            "limit": 5,
            "twist": 0,
            "bend": 2,
            "pull": 0,
            "push": 0,
            "shift": 0,
            "entity": True,
            "rotaxes": "XZ",
            "sizevar": 1.5,
            "generic": 0,
        },
    )
    assert out == {
        "mass": 10.0,
        "box": True,
        "limit": 5.0,
        "bend": 2.0,
        "entity": True,
        "rotaxes": "xz",
        "sizevar": 1.5,
    }


def test_metadata_to_udp_lines_uses_crytools_style() -> None:
    lines = metadata_to_udp_lines(
        {
            "box": True,
            "mass": 10.0,
            "limit": 5.0,
            "entity": True,
            "rotaxes": "xz",
        }
    )
    assert lines == ["box", "mass = 10.0", "limit = 5.0", "entity", "rotaxes = xz"]


def test_serialize_round_trips_metadata() -> None:
    text = serialize_metadata({"mass": 10, "density": None, "box": True})
    assert parse_metadata_text(text) == {"box": True, "mass": 10}


def test_metadata_value_matches_numeric_comparisons() -> None:
    metadata = "mass = 12\ndensity = 3"
    assert metadata_value_matches(metadata, "mass", "=", 12)
    assert metadata_value_matches(metadata, "mass", ">", 11)
    assert metadata_value_matches(metadata, "density", "<", 4)
    assert not metadata_value_matches(metadata, "density", ">", 4)


def test_format_attachment_xml_escapes_name_and_uses_wxyz_order() -> None:
    line = format_attachment_xml("helper&1", (1, 2, 3), (0.5, 0.1, 0.2, 0.3))
    assert 'AName="helper&amp;1"' in line
    assert 'Rotation="0.5,0.1,0.2,0.3"' in line
    assert 'Position="1,2,3"' in line
    assert 'BoneName="bone_helper&amp;1"' in line


def test_audit_crysis3_asset_flags_export_root_and_mesh_problems() -> None:
    issues = audit_crysis3_asset(
        [
            {
                "name": "CryExport_bad-name",
                "type": "EMPTY",
                "export_type": "vehicle",
                "child_count": 0,
                "filename": "bad-name",
            },
            {
                "name": "Hull",
                "type": "MESH",
                "vertices": 3,
                "faces": 1,
                "uv_layers": 0,
                "color_sets": 2,
                "degenerate_faces": 1,
                "scale": (1, 2, 1),
            },
        ],
        fps=24,
    )
    codes = {issue.code for issue in issues}
    assert "time-units" in codes
    assert "export-root-type-invalid" in codes
    assert "export-root-empty" in codes
    assert "export-filename-invalid" in codes
    assert "mesh-no-uv" in codes
    assert "mesh-many-color-sets" in codes
    assert "mesh-degenerate-faces" in codes
    assert "object-non-uniform-scale" in codes


def test_audit_crysis3_asset_flags_skinning_and_material_ids() -> None:
    issues = audit_crysis3_asset(
        [
            {
                "name": "CryExport_character",
                "type": "EMPTY",
                "export_type": "character",
                "child_count": 1,
                "has_skeleton": False,
            },
            {
                "name": "Body",
                "type": "MESH",
                "vertices": 10,
                "faces": 4,
                "uv_layers": 1,
                "is_skinned": True,
                "has_armature": False,
                "bad_weight_totals": 2,
                "too_many_influences": 1,
            },
        ],
        [
            {"name": "mat_body", "material_id": 0, "physicalize": "Default"},
            {"name": "mat_proxy", "material_id": 2, "physicalize": "Mystery"},
            {"name": "mat_dup", "material_id": 2},
        ],
    )
    codes = {issue.code for issue in issues}
    assert "character-no-skeleton" in codes
    assert "skin-no-armature-modifier" in codes
    assert "skin-weights-not-normalized" in codes
    assert "skin-too-many-influences" in codes
    assert "material-physicalize-unknown" in codes
    assert "material-id-duplicate" in codes
    assert "material-id-hole" in codes


def test_format_crysis3_audit_report_summarizes_findings() -> None:
    issues = audit_crysis3_asset(
        [
            {
                "name": "CryExport_prop",
                "type": "EMPTY",
                "export_type": "static_geometry",
                "child_count": 1,
            },
            {
                "name": "prop_group",
                "type": "MESH",
                "vertices": 4,
                "faces": 2,
                "uv_layers": 1,
            },
        ],
        fps=30,
        unit_system="METRIC",
    )
    report = format_crysis3_audit_report(issues)
    assert report == "Crysis 3 Asset Audit\nNo issues found."


def test_profile_audit_uses_c1_export_node_and_skin_limits() -> None:
    issues = audit_crytools_asset(
        [
            {
                "name": "truck_CryExportNode",
                "type": "EMPTY",
                "child_count": 1,
            },
            {
                "name": "truck-LOD2-hull-piece01",
                "type": "MESH",
                "vertices": 8,
                "faces": 4,
                "uv_layers": 1,
                "is_skinned": True,
                "has_armature": True,
                "too_many_influences": 1,
            },
        ],
        profile=CRYSIS1,
        fps=30,
    )
    codes = {issue.code for issue in issues}
    assert "export-root-type-missing" not in codes
    assert "c1-lod-marker" in codes
    assert "c1-breakable-piece" in codes
    assert "skin-too-many-influences" in codes
    assert any("5-influence" in issue.message for issue in issues)


def test_profile_report_title_uses_target_label() -> None:
    assert format_crytools_audit_report([], profile=CRYSIS1) == "Crysis 1 / CE2 Asset Audit\nNo issues found."
    assert format_crytools_audit_report([], profile=CRYSIS3) == "Crysis 3 Asset Audit\nNo issues found."
