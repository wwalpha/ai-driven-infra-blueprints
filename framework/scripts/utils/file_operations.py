"""Generic file publication and best-effort rollback."""

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


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


def atomic_files(contents, staging_directory=None):
    originals = {path: path.read_bytes() if path.exists() else None for path in contents}
    staged, published = {}, []
    try:
        for path, text in contents.items():
            if text is None:
                staged[path] = None
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=staging_directory or path.parent, delete=False) as stream:
                staged[path] = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
        for path, temporary in staged.items():
            published.append(path)
            if temporary is None:
                path.unlink()
            else:
                os.replace(temporary, path)
    except BaseException:
        for path in reversed(published):
            if staged[path] is not None and staged[path].exists():  # Rename did not consume the staged file.
                continue
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                with tempfile.NamedTemporaryFile(dir=staging_directory or path.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(originals[path])
                os.replace(temporary, path)
        raise
    finally:
        for temporary in staged.values():
            if temporary is not None:
                temporary.unlink(missing_ok=True)



def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def evidence_store(root, *, create=True):
    """Private local seal, outside Git; not AWS credentials or a response snapshot."""
    base = Path(tempfile.gettempdir()).resolve() / ('blueprint-import-' + digest(str(Path.home()))[:16])
    directory = base / digest(str(root.resolve()))
    for path in (base, directory):
        if not create and not path.exists() and not path.is_symlink():
            return directory
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
            raise ValueError('IMPORT unsafe temporary evidence directory')
        if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError('IMPORT evidence directory must be private to the current user')
    return directory



def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
