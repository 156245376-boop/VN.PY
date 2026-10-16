"""封存必须可恢复；损坏或越界输入不得写入恢复目录。"""

from __future__ import annotations

import hashlib
import importlib
import json
import warnings
import zipfile
from pathlib import Path

import pytest

FILES = {"empty.txt": b"", ".hidden": b"abc", "策略/规则.txt": "交易".encode()}
METADATA = {"git-status.txt": b" M old.py\n", "working-tree.patch": b"", "exclusions.json": b"[]"}


@pytest.fixture
def verifier():
    assert (Path(__file__).parents[1] / "tools/verify_archive.py").is_file(), (
        "archive verification module is not implemented"
    )
    return importlib.import_module("tools.verify_archive")


def make_archive(
    directory: Path, change: str = "", unsafe_name: str = "", files: dict[str, bytes] | None = None
) -> tuple[Path, str]:
    contents = FILES if files is None else files
    entries = [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in contents.items()
    ]
    if change == "inner_hash":
        entries[0]["sha256"] = "0" * 64
    if change == "case_collision":
        entries.append({"path": ".HIDDEN", "size": 3, "sha256": hashlib.sha256(b"abc").hexdigest()})
    path = directory / "snapshot.zip"
    with warnings.catch_warnings(), zipfile.ZipFile(path, "x") as archive:
        warnings.simplefilter("ignore", UserWarning)
        for name, data in contents.items():
            if change != "missing" or name != "empty.txt":
                archive.writestr("project/" + name, data)
        archive.writestr(
            "metadata/manifest.json", json.dumps({"schema_version": 1, "entries": entries})
        )
        for name, data in METADATA.items():
            archive.writestr("metadata/" + name, data)
        if change == "extra":
            archive.writestr("metadata/extra.txt", b"unexpected")
        elif change == "duplicate":
            archive.writestr("project/empty.txt", b"")
        elif change == "symlink":
            info = zipfile.ZipInfo("project/link")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            archive.writestr(info, b"../outside")
        elif change == "case_collision":
            archive.writestr("project/.HIDDEN", b"abc")
        elif unsafe_name:
            archive.writestr(unsafe_name, b"unexpected")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_roundtrip_preserves_empty_hidden_unicode_files(tmp_path, verifier):
    archive, checksum = make_archive(tmp_path)
    destination = tmp_path / "restore"
    report = verifier.extract_verified_archive(
        archive, checksum, destination, forbidden_root=tmp_path / "workspace"
    )
    restored = {
        path.relative_to(destination / "project").as_posix(): path.read_bytes()
        for path in (destination / "project").rglob("*")
        if path.is_file()
    }
    assert restored == FILES
    assert report == {"file_count": 3, "source_bytes": 9}


@pytest.mark.parametrize("change", ["outer_hash", "inner_hash"])
def test_corruption_is_rejected(tmp_path, verifier, change):
    archive, checksum = make_archive(tmp_path, change)
    if change == "outer_hash":
        checksum = "0" * 64
    with pytest.raises(verifier.ArchiveError):
        verifier.verify_archive(archive, checksum)


@pytest.mark.parametrize(
    ("change", "unsafe_name"),
    [
        ("duplicate", ""), ("symlink", ""), ("case_collision", ""),
        ("", "../escaped.txt"), ("", "/absolute.txt"), ("", "C:/escaped.txt"),
        ("", "project/../escaped.txt"), ("", "project\\escaped.txt"),
    ],
)
def test_unsafe_or_duplicate_members_are_rejected(tmp_path, verifier, change, unsafe_name):
    archive, checksum = make_archive(tmp_path, change, unsafe_name)
    destination = tmp_path / "restore"
    with pytest.raises(verifier.ArchiveError):
        verifier.extract_verified_archive(
            archive, checksum, destination, forbidden_root=tmp_path / "workspace"
        )
    assert not destination.exists()
    assert not (tmp_path / "escaped.txt").exists()


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_member_set_mismatch_is_rejected(tmp_path, verifier, change):
    archive, checksum = make_archive(tmp_path, change)
    with pytest.raises(verifier.ArchiveError):
        verifier.verify_archive(archive, checksum)


@pytest.mark.parametrize("inside_workspace", [True, False])
def test_restore_refuses_workspace_or_nonempty_destination(tmp_path, verifier, inside_workspace):
    archive, checksum = make_archive(tmp_path)
    workspace = tmp_path / "workspace"
    destination = workspace / "restore" if inside_workspace else tmp_path / "restore"
    destination.mkdir(parents=True)
    keep = destination / "keep.txt"
    keep.write_bytes(b"keep")
    with pytest.raises(verifier.ArchiveError):
        verifier.extract_verified_archive(archive, checksum, destination, forbidden_root=workspace)
    assert keep.read_bytes() == b"keep"
    assert list(destination.iterdir()) == [keep]


def test_restore_uses_verified_bytes_when_archive_is_replaced(tmp_path, verifier, monkeypatch):
    archive, checksum = make_archive(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    replacement, _ = make_archive(other, files={**FILES, ".hidden": b"BAD"})
    replacement_bytes = replacement.read_bytes()
    original_close = zipfile.ZipFile.close
    swapped = []

    def close_then_replace(instance):
        original_close(instance)
        if not swapped:
            swapped.append(True)
            archive.write_bytes(replacement_bytes)

    monkeypatch.setattr(zipfile.ZipFile, "close", close_then_replace)
    destination = tmp_path / "restore"
    report = verifier.extract_verified_archive(
        archive, checksum, destination, forbidden_root=tmp_path / "workspace"
    )
    assert swapped
    assert report == {"file_count": 3, "source_bytes": 9}
    assert (destination / "project/.hidden").read_bytes() == b"abc"
