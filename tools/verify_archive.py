"""验证旧成果封存包；恢复操作只允许写入活动项目之外的空目录。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

METADATA = {
    "metadata/manifest.json", "metadata/git-status.txt",
    "metadata/working-tree.patch", "metadata/exclusions.json",
}


class ArchiveError(ValueError):
    """封存包损坏、成员不安全或恢复目标不符合要求。"""


def _safe_name(name: str) -> None:
    parts = name.split("/")
    if not name or any(p in {"", ".", ".."} for p in parts) or "\\" in name or ":" in name:
        raise ArchiveError(f"Unsafe archive path: {name!r}")
    for part in parts:
        stem = part.split(".")[0].upper()
        if (
            part.endswith((" ", ".")) or any(ord(c) < 32 for c in part)
            or any(c in '<>"|?*' for c in part)
            or stem in {"CON", "PRN", "AUX", "NUL"}
            or re.fullmatch(r"(?:COM|LPT)[1-9]", stem)
        ):
            raise ArchiveError(f"Unsafe Windows path: {name!r}")


def _inspect(archive_path: Path, expected_sha256: str) -> tuple[bytes, dict[str, int]]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ArchiveError("Invalid SHA256")
    if archive_path.stat().st_size > 64 * 1024 * 1024:
        raise ArchiveError("Archive exceeds source-snapshot size limit")
    snapshot = archive_path.read_bytes()
    if hashlib.sha256(snapshot).hexdigest() != expected_sha256:
        raise ArchiveError("Archive SHA256 mismatch")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(name.casefold() for name in names)):
            raise ArchiveError("Duplicate or case-colliding archive members")
        if sum(info.file_size for info in infos) > 128 * 1024 * 1024:
            raise ArchiveError("Expanded archive exceeds source-snapshot size limit")
        for info in infos:
            _safe_name(info.filename)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if info.is_dir() or mode not in {0, stat.S_IFREG} or info.flag_bits & 1:
                raise ArchiveError("Unsupported archive member type")
        manifest = json.loads(archive.read("metadata/manifest.json"))
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("entries"), list):
            raise ArchiveError("Unsupported manifest schema")
        expected = set(METADATA)
        paths = set()
        total = 0
        for entry in manifest["entries"]:
            name, size, checksum = entry["path"], entry["size"], entry["sha256"]
            _safe_name(name)
            if name.casefold() in paths or type(size) is not int or size < 0:
                raise ArchiveError("Invalid manifest entry")
            paths.add(name.casefold())
            member = "project/" + name
            expected.add(member)
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ArchiveError("Invalid file SHA256")
            data = archive.read(member)
            if len(data) != size or hashlib.sha256(data).hexdigest() != checksum:
                raise ArchiveError(f"Source content mismatch: {name}")
            total += size
        if set(names) != expected:
            raise ArchiveError("Archive member set does not match manifest")
    return snapshot, {"file_count": len(paths), "source_bytes": total}


def _verified_snapshot(archive_path: Path, expected_sha256: str) -> tuple[bytes, dict[str, int]]:
    try:
        return _inspect(archive_path, expected_sha256)
    except (OSError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, ValueError) as exc:
        if isinstance(exc, ArchiveError):
            raise
        raise ArchiveError(f"Invalid archive: {exc}") from exc


def verify_archive(archive_path: Path, expected_sha256: str) -> dict[str, int]:
    """核对整体哈希、完整成员集合及每个源文件的字节。"""
    return _verified_snapshot(archive_path, expected_sha256)[1]


def extract_verified_archive(
    archive_path: Path, expected_sha256: str, destination: Path, *, forbidden_root: Path
) -> dict[str, int]:
    """验包通过后恢复至工作区外的空目录，始终禁止覆盖。"""
    snapshot, report = _verified_snapshot(archive_path, expected_sha256)
    target = destination.resolve()
    if destination.is_symlink() or target.is_relative_to(forbidden_root.resolve()):
        raise ArchiveError("Restoration inside the active workspace is forbidden")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ArchiveError("Restoration destination must be empty")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        for info in archive.infolist():
            path = target.joinpath(*PurePosixPath(info.filename).parts)
            if not path.resolve().is_relative_to(target):
                raise ArchiveError("Restoration path escaped destination")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(archive.read(info))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sha256-file", required=True, type=Path)
    parser.add_argument("--extract-to", type=Path)
    args = parser.parse_args()
    try:
        record = args.sha256_file.read_text(encoding="ascii").split()
        if len(record) != 2 or record[1] != args.archive.name:
            raise ArchiveError("Checksum record must name this archive")
        if args.extract_to:
            report = extract_verified_archive(
                args.archive, record[0], args.extract_to,
                forbidden_root=Path(__file__).resolve().parents[1],
            )
        else:
            report = verify_archive(args.archive, record[0])
        print(json.dumps({"status": "ok", **report}))
        return 0
    except (ArchiveError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
