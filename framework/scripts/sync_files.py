"""Service file publication and best-effort rollback; no selection or validation."""

from pathlib import Path

from utils.file_operations import restore_files
from utils.input_cache import input_bytes, input_is_file


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


def markdown_newlines(path, content):
    """Preserve the existing view's line endings without changing generated content."""
    if not input_is_file(path):
        return content
    original = input_bytes(path)
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
