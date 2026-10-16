"""Service file publication and best-effort rollback; no selection or validation."""

import os
import tempfile
from pathlib import Path


def changed_files(expected: dict[Path, str]) -> dict[Path, str]:
    """Compare the bytes publication would write, including preserved Markdown newlines."""
    expected = {path: markdown_newlines(path, content) if path.suffix == ".md" else content
                for path, content in expected.items()}
    return {path: content for path, content in expected.items()
            if not path.is_file() or path.read_bytes() != content.encode("utf-8")}


def save_files(expected: dict[Path, str]) -> None:
    """Rollback this service if a filesystem write fails after successful generation."""
    expected = {path: markdown_newlines(path, content) if path.suffix == ".md" else content
                for path, content in expected.items()}
    originals = {path: path.read_bytes() if path.is_file() else None for path in expected}
    written = []
    try:
        for path, content in expected.items():
            if originals[path] == content.encode("utf-8"):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            written.append(path)
            path.write_text(content, encoding="utf-8", newline="")
    except OSError as error:
        try:
            restore_files({path: originals[path] for path in reversed(written)})
        except OSError as rollback_error:
            raise OSError(f"{error}; generated-file rollback failed: {rollback_error}") from error
        raise


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




def markdown_newlines(path, content):
    """Preserve the existing view's line endings without changing generated content."""
    if not path.is_file():
        return content
    original = path.read_bytes()
    bare = original.replace(b"\r\n", b"")
    if b"\r" in bare:
        raise ValueError(f"unsupported Markdown newline: {path}")
    if b"\r\n" in original and b"\n" in bare:
        raise ValueError(f"mixed Markdown newlines: {path}")
    content = content.replace("\r\n", "\n")
    if not original.endswith(b"\n") and content.endswith("\n"):
        content = content[:-1]
    elif original.endswith(b"\n") and not content.endswith("\n"):
        content += "\n"
    return content.replace("\n", "\r\n") if b"\r\n" in original else content


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

