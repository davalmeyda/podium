"""State helpers (ARCHITECTURE.md section 7): ledger, lock, atomic writes, backups."""
from __future__ import annotations

import binascii
import contextlib
import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union

LEDGER_NAME = "owned.json"
LOCK_NAME = "lock"
LOCK_STALE_SECONDS = 600  # a lock older than 10 minutes is considered abandoned


class StateError(Exception):
    """The state directory, ledger or lock cannot be used (environment error)."""


# --------------------------------------------------------------------------- hashing

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- writes

def atomic_write(path: Path, data: Union[bytes, str]) -> None:
    """Write `data` to `path` atomically (temp file in the same dir + os.replace)."""
    path = Path(path)
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o644
    try:
        mode = path.stat().st_mode & 0o7777
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".%s." % path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def backup(path: Path, now: Optional[datetime] = None) -> Path:
    """Copy `path` to `<path>.bak-podium-<YYYYMMDD-HHMMSS>-<4hex>` and return the copy."""
    path = Path(path)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    for _ in range(20):
        suffix = binascii.hexlify(os.urandom(2)).decode("ascii")
        target = path.with_name("%s.bak-podium-%s-%s" % (path.name, stamp, suffix))
        if not target.exists():
            shutil.copy2(str(path), str(target))
            return target
    raise StateError("cannot find a free backup name for %s" % path)  # pragma: no cover


# --------------------------------------------------------------------------- lock

@contextlib.contextmanager
def lock(state_dir: Path, stale_seconds: int = LOCK_STALE_SECONDS) -> Iterator[Path]:
    """Exclusive run lock `state_dir/lock`; a lock older than `stale_seconds` is taken over."""
    path = Path(state_dir) / LOCK_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StateError("cannot create state directory %s: %s" % (path.parent, exc))
    fd = -1
    for _ in range(3):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > stale_seconds:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(str(path))
                continue
            raise StateError("another podium run is in progress (lock: %s)" % path)
    if fd < 0:
        raise StateError("cannot acquire lock %s" % path)
    try:
        os.write(fd, ("%d\n" % os.getpid()).encode("ascii"))
    finally:
        os.close(fd)
    try:
        yield path
    finally:
        with contextlib.suppress(OSError):
            os.unlink(str(path))


# --------------------------------------------------------------------------- ledger

class Ledger:
    """`state_dir/owned.json`: {"files": {abs_path: sha256}, "json": {abs_path: {pointer: {...}}},
    "adopted": {abs_path: backup_path}} ("adopted" lists foreign files taken over with --adopt)."""

    def __init__(self, path: Path, files: Optional[Dict[str, str]] = None,
                 json_keys: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
                 adopted: Optional[Dict[str, str]] = None) -> None:
        self.path = Path(path)
        self.files: Dict[str, str] = files if files is not None else {}
        self.json: Dict[str, Dict[str, Dict[str, Any]]] = json_keys if json_keys is not None else {}
        self.adopted: Dict[str, str] = adopted if adopted is not None else {}

    @classmethod
    def load(cls, state_dir: Path) -> "Ledger":
        path = Path(state_dir) / LEDGER_NAME
        if not path.exists():
            return cls(path)
        try:
            with open(str(path), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            raise StateError("cannot read ledger %s: %s" % (path, exc))
        if not isinstance(data, dict) or not isinstance(data.get("files", {}), dict) \
                or not isinstance(data.get("json", {}), dict) or not isinstance(data.get("adopted", {}), dict):
            raise StateError("ledger %s has an unexpected shape" % path)
        return cls(path, dict(data.get("files", {})), dict(data.get("json", {})), dict(data.get("adopted", {})))

    def is_empty(self) -> bool:
        return not self.files and not any(self.json.values())

    def save(self) -> None:
        for key in [k for k, v in self.json.items() if not v]:
            del self.json[key]
        document: Dict[str, Any] = {"files": self.files, "json": self.json}
        if self.adopted:
            document["adopted"] = self.adopted
        payload = json.dumps(document, indent=2, ensure_ascii=False)
        atomic_write(self.path, payload + "\n")

    def delete(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(str(self.path))
