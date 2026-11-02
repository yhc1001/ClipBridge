from __future__ import annotations

import hashlib
import os
import shutil
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .model import CHUNK, MAX_FILES, safe_relative, valid_id


def assert_local_regular(path: Path):
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("UNC/network sources are not supported")
    for part in [path, *path.parents]:
        info = part.lstat()
        if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400) or part.is_symlink():
            raise ValueError("reparse points are not supported")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
        raise ValueError("not a regular file/directory")
    return info


def scan_sources(paths: list[str], limit: int, cancelled=lambda: False, *, hash_files=True):
    entries, sources, roots, total, names = [], {}, [], 0, set()
    if not paths or len(paths) > MAX_FILES:
        raise ValueError("file count limit")

    def add(source: Path, relative: str):
        nonlocal total
        if cancelled():
            raise InterruptedError("superseded")
        safe_relative(relative)
        if relative.casefold() in names or len(entries) >= MAX_FILES:
            raise ValueError("file count/collision")
        names.add(relative.casefold())
        info = assert_local_regular(source)
        if source.is_dir():
            entries.append({"path": relative, "kind": "dir", "size": 0})
            for child in sorted(source.iterdir(), key=lambda p: p.name.casefold()):
                add(child, relative + "/" + child.name)
        else:
            total += info.st_size
            if total > limit:
                raise ValueError("file size limit")
            entry = {"path": relative, "kind": "file", "size": info.st_size}
            if hash_files:
                digest = hashlib.sha256()
                with source.open("rb") as stream:
                    while chunk := stream.read(CHUNK):
                        if cancelled():
                            raise InterruptedError("superseded")
                        digest.update(chunk)
                after = source.stat()
                if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("source changed during transfer")
                entry["sha256"] = digest.hexdigest()
            entries.append(entry)
            sources[relative] = source

    for path in paths:
        source = Path(path).absolute()
        safe_relative(source.name)
        roots.append(source.name)
        add(source, source.name)
    return {"entries": entries, "roots": roots, "total": total}, sources


def validate_manifest(value, limit, *, streaming=False):
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list) or not 0 < len(value["entries"]) <= MAX_FILES:
        raise ValueError("invalid manifest")
    roots, entries = value.get("roots"), value["entries"]
    if not isinstance(roots, list) or not roots or len(roots) > MAX_FILES:
        raise ValueError("invalid roots")
    if len(set(root.casefold() for root in roots if isinstance(root, str))) != len(roots):
        raise ValueError("root collision")
    for root in roots:
        if "/" in safe_relative(root):
            raise ValueError("invalid root")
    names, total = {}, 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid entry")
        path = safe_relative(entry.get("path"))
        folded = path.casefold()
        kind, size = entry.get("kind"), entry.get("size")
        if folded in names or kind not in ("file", "dir") or type(size) is not int or not 0 <= size <= limit or (kind == "dir" and size != 0):
            raise ValueError("invalid entry size/type/collision")
        if kind == "file" and (not streaming or "sha256" in entry):
            digest = entry.get("sha256", "")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("invalid hash")
        names[folded] = kind
        total += size
        if total > limit or path.split("/")[0].casefold() not in {r.casefold() for r in roots}:
            raise ValueError("file size/root limit")
    for root in roots:
        if root.casefold() not in names:
            raise ValueError("missing root")
    for path in names:
        parts = path.split("/")
        for index in range(1, len(parts)):
            if names.get("/".join(parts[:index])) != "dir":
                raise ValueError("missing directory parent")
    if type(value.get("total")) is not int or total != value["total"]:
        raise ValueError("incorrect total")
    return value


class ReceiveTransfer:
    def __init__(self, parent: Path, transfer_id: str, manifest: dict, *, streaming=False):
        valid_id(transfer_id)
        if manifest["total"] > shutil.disk_usage(parent).free:
            raise ValueError("파일을 받을 임시 저장 공간이 부족합니다.")
        self.directory = parent / transfer_id
        self.directory.mkdir(exist_ok=False)
        self.manifest = manifest
        self.streaming = streaming
        self.lock = threading.RLock()
        self.stream, self.stream_name = None, None
        self.entries = {e["path"]: e for e in manifest["entries"] if e["kind"] == "file"}
        self.offsets = {name: 0 for name in self.entries}
        self.hashes = {name: hashlib.sha256() for name in self.entries}
        self.updated = time.monotonic()
        self.received = 0
        try:
            for entry in sorted(manifest["entries"], key=lambda e: e["path"].count("/")):
                target = self.directory.joinpath(*entry["path"].split("/"))
                if entry["kind"] == "dir":
                    target.mkdir()
                else:
                    target.touch(exist_ok=False)
        except Exception:
            self.remove()
            raise

    def chunk(self, name: str, offset: int, data: bytes):
        with self.lock:
            self._chunk(name, offset, data)

    def _close_stream(self):
        if self.stream:
            stream = self.stream
            self.stream, self.stream_name = None, None
            stream.close()

    def _chunk(self, name: str, offset: int, data: bytes):
        entry = self.entries.get(name)
        if not entry or type(offset) is not int or offset != self.offsets[name] or not 0 < len(data) <= CHUNK or offset + len(data) > entry["size"]:
            raise ValueError("invalid chunk")
        if name != self.stream_name:
            self._close_stream()
            target = self.directory.joinpath(*name.split("/"))
            assert_local_regular(target)
            self.stream = target.open("r+b")
            self.stream_name = name
        self.stream.seek(offset)
        self.stream.write(data)
        self.hashes[name].update(data)
        self.offsets[name] += len(data)
        self.received += len(data)
        self.updated = time.monotonic()

    def finish(self, hashes=None):
        with self.lock:
            self._close_stream()
            if self.streaming and (not isinstance(hashes, dict) or hashes.keys() != self.entries.keys()):
                raise ValueError("missing final file hashes")
            for name, entry in self.entries.items():
                expected = hashes[name] if self.streaming else entry["sha256"]
                if (not isinstance(expected, str) or len(expected) != 64 or
                        ("sha256" in entry and expected != entry["sha256"]) or
                        self.offsets[name] != entry["size"] or self.hashes[name].hexdigest() != expected):
                    raise ValueError("file integrity check failed")
            return [str(self.directory / name) for name in self.manifest["roots"]]

    def remove(self):
        with self.lock:
            try:
                self._close_stream()
            finally:
                shutil.rmtree(self.directory, ignore_errors=True)


class TransferStore:
    def __init__(self, base: Path):
        self.base = base / "transfers"
        # A single-instance mutex is acquired before this store is created.
        self.base.mkdir(parents=True, exist_ok=True)
        assert_local_regular(self.base)
        if self.base.is_symlink() or getattr(self.base.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("unsafe transfer directory")
        for directory in self.base.iterdir():
            try:
                valid_id(directory.name)
                if directory.is_dir() and not directory.is_symlink():
                    shutil.rmtree(directory)
            except (ValueError, OSError):
                pass
        self.retained: ReceiveTransfer | None = None
        self.transfers = {}
        self.pins = {}

    def retain(self, transfer: ReceiveTransfer):
        previous = self.retained
        self.retained = transfer
        self.transfers[transfer.directory.name] = transfer
        if previous:
            self._collect(previous.directory.name)

    def _collect(self, key):
        transfer = self.transfers.get(key)
        if transfer and transfer is not self.retained and not self.pins.get(key):
            transfer.remove()
            self.transfers.pop(key, None)
            self.pins.pop(key, None)

    def pin(self, paths):
        # Keep staged files alive until every recipient has finished reading them.
        keys = {key for key, transfer in self.transfers.items()
                if any(Path(path).is_relative_to(transfer.directory) for path in paths)}
        for key in keys:
            self.pins[key] = self.pins.get(key, 0) + 1
        return keys

    def release(self, keys):
        for key in keys:
            self.pins[key] = max(0, self.pins.get(key, 0) - 1)
            self._collect(key)

    def close(self):
        for transfer in self.transfers.values():
            transfer.remove()
        self.retained = None
        self.transfers.clear()
        self.pins.clear()
        # Also remove a stage whose constructor finished during task cancellation.
        for directory in self.base.iterdir():
            try:
                valid_id(directory.name)
                if directory.is_dir() and not directory.is_symlink():
                    shutil.rmtree(directory)
            except (ValueError, OSError):
                pass
