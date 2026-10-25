"""Private signed evidence shared independently of workflow policy."""

import hmac
import json
import os
import secrets
import stat
import tempfile
from pathlib import Path

from utils.file_operations import atomic_files
from utils.json_format import document_sha256, json_text


def evidence_store(root, *, create=True):
    """Private local seal, outside Git; not AWS credentials or a response snapshot."""
    base = Path(tempfile.gettempdir()).resolve() / (
        "blueprint-import-" + document_sha256(str(Path.home()))[:16]
    )
    directory = base / document_sha256(str(root.resolve()))
    for path in (base, directory):
        if not create and not path.exists() and not path.is_symlink():
            return directory
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
            raise ValueError("IMPORT unsafe temporary evidence directory")
        if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError(
                "IMPORT evidence directory must be private to the current user"
            )
    return directory


def seal_key(root):
    path = evidence_store(root) / "seal.key"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = None
    if descriptor is not None:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    if (
        path.is_symlink()
        or not path.is_file()
        or (
            os.name != "nt"
            and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077)
        )
    ):
        raise ValueError("IMPORT unsafe local evidence seal")
    value = path.read_bytes()
    if len(value) != 32:
        raise ValueError("IMPORT invalid local evidence seal")
    return value


def sealed(root, value):
    payload = json_text(value)
    return (
        json_text(
            {
                "payload": value,
                "signature": hmac.new(
                    seal_key(root), payload.encode("utf-8"), "sha256"
                ).hexdigest(),
            }
        )
        + "\n"
    )


def read_sealed(root, file):
    if file.is_symlink():
        raise ValueError("IMPORT symlink evidence is forbidden")
    envelope = json.loads(file.read_text(encoding="utf-8"))
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"payload", "signature"}
        or not isinstance(envelope["signature"], str)
    ):
        raise ValueError("IMPORT invalid sealed evidence")
    expected = hmac.new(
        seal_key(root), json_text(envelope["payload"]).encode("utf-8"), "sha256"
    ).hexdigest()
    if not hmac.compare_digest(expected, envelope["signature"]):
        raise ValueError("IMPORT acquisition evidence was modified")
    return envelope["payload"]


def write_sealed(root, file, value):
    if file.is_symlink():
        raise ValueError("IMPORT symlink evidence is forbidden")
    atomic_files({file: sealed(root, value)}, staging_directory=file.parent)
