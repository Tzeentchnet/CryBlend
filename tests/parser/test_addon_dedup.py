"""Pure-Python unit tests for the bulk-import dedup helper.

The helper is split out into ``cryengine_importer.blender.import_dedup``
specifically so it has zero ``bpy`` coupling and can be exercised here
without a Blender install.
"""

from __future__ import annotations

import sys

import pytest

from cryengine_importer.blender.import_dedup import canonicalize_import_paths


def _touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def test_drops_companion_when_primary_present_in_batch(tmp_path):
    primary = tmp_path / "foo.cgf"
    companion = tmp_path / "foo.cgfm"
    _touch(primary)
    _touch(companion)

    kept, skipped = canonicalize_import_paths([str(primary), str(companion)])

    assert kept == [str(primary)]
    assert skipped == 1


def test_keeps_companion_only_drop_when_primary_on_disk_but_not_in_batch(
    tmp_path,
):
    # Companion is dropped without the primary in the batch — even
    # though the primary exists on disk, we keep the companion. The
    # CryEngine.process redirect will load the primary instead at
    # parse time, so the asset is still imported once.
    primary = tmp_path / "foo.cgf"
    companion = tmp_path / "foo.cgfm"
    _touch(primary)
    _touch(companion)

    kept, skipped = canonicalize_import_paths([str(companion)])

    assert kept == [str(companion)]
    assert skipped == 0


def test_keeps_companion_with_no_primary_on_disk(tmp_path):
    companion = tmp_path / "foo.cgfm"
    _touch(companion)

    kept, skipped = canonicalize_import_paths([str(companion)])

    assert kept == [str(companion)]
    assert skipped == 0


def test_keeps_unrelated_assets(tmp_path):
    a = tmp_path / "a.cgf"
    b = tmp_path / "b.cga"
    _touch(a)
    _touch(b)

    kept, skipped = canonicalize_import_paths([str(a), str(b)])

    assert kept == [str(a), str(b)]
    assert skipped == 0


@pytest.mark.parametrize(
    "primary_ext,companion_ext",
    [(".cga", ".cgam"), (".chr", ".chrm"), (".skin", ".skinm")],
)
def test_drops_each_companion_kind(tmp_path, primary_ext, companion_ext):
    primary = tmp_path / f"foo{primary_ext}"
    companion = tmp_path / f"foo{companion_ext}"
    _touch(primary)
    _touch(companion)

    kept, skipped = canonicalize_import_paths([str(primary), str(companion)])

    assert kept == [str(primary)]
    assert skipped == 1


def test_dedupes_exact_path_duplicates(tmp_path):
    p = tmp_path / "foo.cgf"
    _touch(p)

    kept, skipped = canonicalize_import_paths([str(p), str(p)])

    assert kept == [str(p)]
    assert skipped == 0


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="case-insensitive dedup relies on NTFS semantics",
)
def test_dedupes_case_variants_on_windows(tmp_path):
    p = tmp_path / "Foo.CGF"
    _touch(p)
    variant = str(p).lower()

    kept, skipped = canonicalize_import_paths([str(p), variant])

    assert len(kept) == 1
    assert skipped == 0


def test_preserves_input_ordering(tmp_path):
    a = tmp_path / "a.cgf"
    b = tmp_path / "b.cgf"
    c = tmp_path / "c.cgf"
    for f in (a, b, c):
        _touch(f)

    kept, _ = canonicalize_import_paths([str(c), str(a), str(b)])

    assert kept == [str(c), str(a), str(b)]


def test_companion_only_with_no_primary_when_other_primary_in_batch(tmp_path):
    # Edge case: a companion whose own primary is absent shouldn't be
    # affected by an unrelated primary being in the batch.
    other_primary = tmp_path / "bar.cgf"
    companion = tmp_path / "foo.cgfm"
    _touch(other_primary)
    _touch(companion)

    kept, skipped = canonicalize_import_paths(
        [str(other_primary), str(companion)]
    )

    assert sorted(kept) == sorted([str(other_primary), str(companion)])
    assert skipped == 0
