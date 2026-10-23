"""Generic file publication and best-effort rollback."""

import hashlib
import os
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



def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
