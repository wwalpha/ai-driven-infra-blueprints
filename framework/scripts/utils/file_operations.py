"""Generic file publication and best-effort rollback."""

import hashlib
import os
import uuid
from pathlib import Path


def stage_file(
    path: Path, content: str | bytes, *, fsync: bool = False,
    newline: str | None = None, mode: int = 0o600,
    staging_directory: Path | None = None,
) -> Path:
    """Write a unique sibling; mode follows os.open's normal umask handling."""
    directory = Path(staging_directory) if staging_directory is not None else path.parent
    while True:
        temporary = directory / ('tmp' + uuid.uuid4().hex)
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            break
        except FileExistsError:
            continue
    try:
        stream = os.fdopen(descriptor, 'wb' if isinstance(content, bytes) else 'w',
                           encoding=None if isinstance(content, bytes) else 'utf-8',
                           newline=None if isinstance(content, bytes) else newline)
    except BaseException:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    try:
        with stream:
            stream.write(content)
            if fsync:
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def publish_staged(temporary: Path, path: Path) -> None:
    """Replace one file, retaining no unused stage on failure."""
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_replace_file(
    path: Path, content: str | bytes, *, fsync: bool = False, mode: int = 0o600,
) -> None:
    """Stage and publish one file; serialization and transactions belong to callers."""
    publish_staged(stage_file(path, content, fsync=fsync, mode=mode), path)


def restore_files(originals: dict[Path, bytes | None]) -> None:
    errors = []
    for path, content in originals.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            elif not path.is_file() or path.read_bytes() != content:
                path.write_bytes(content)
        except OSError as error:
            errors.append(f"{path}: {error}")
    if errors:
        raise OSError("; ".join(errors))


def atomic_files(contents: dict[Path, str | None], staging_directory: Path | None = None) -> None:
    originals = {path: path.read_bytes() if path.exists() else None for path in contents}
    staged, published = {}, []
    try:
        for path, text in contents.items():
            if text is None:
                staged[path] = None
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            staged[path] = stage_file(path, text, fsync=True, newline='', staging_directory=staging_directory)
        for path, temporary in staged.items():
            published.append(path)
            if temporary is None:
                path.unlink()
            else:
                # Rollback needs the unconsumed stage to distinguish a failed rename.
                os.replace(temporary, path)
    except BaseException:
        for path in reversed(published):
            if staged[path] is not None and staged[path].exists():  # Rename did not consume the staged file.
                continue
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                publish_staged(stage_file(path, originals[path], staging_directory=staging_directory), path)
        raise
    finally:
        for temporary in staged.values():
            if temporary is not None:
                temporary.unlink(missing_ok=True)



def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
