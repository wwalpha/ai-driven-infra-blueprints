"""Private, atomic local records without cryptographic keys."""

import json
import os
import stat

from utils.file_operations import atomic_replace_file
from utils.json_format import json_text
from utils.sealed_evidence import evidence_store as shared_store


def evidence_store(root, *, create=True):
    path = shared_store(root, create=create) / "deploy-current-v3"
    if not create and not path.exists() and not path.is_symlink():
        return path
    path.mkdir(mode=0o700, exist_ok=True)
    private(path, directory=True)
    return path


def private(path, *, directory=False):
    info = path.lstat()
    if (
        path.is_symlink()
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or os.name != "nt"
        and (info.st_uid != os.getuid() or info.st_mode & 0o077)
        or not directory
        and info.st_nlink != 1
    ):
        raise ValueError("unsafe local evidence: " + str(path))


def read_sealed(root, file):
    private(file)
    value = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"payload"}:
        raise ValueError("invalid local evidence")
    return value["payload"]


def sealed(root, value):
    return json_text({"payload": value}) + "\n"


def write_sealed(root, file, value):
    if file.exists() or file.is_symlink():
        private(file)
    atomic_replace_file(file, sealed(root, value), fsync=True, mode=0o600)
