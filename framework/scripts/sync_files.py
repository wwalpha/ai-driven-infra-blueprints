"""Service file publication and best-effort rollback; no selection or validation."""

from pathlib import Path


def save_files(expected: dict[Path, str]) -> None:
    """Rollback this service if a filesystem write fails after successful generation."""
    originals = {path: path.read_bytes() if path.is_file() else None for path in expected}
    written = []
    try:
        for path, content in expected.items():
            if originals[path] == content.encode("utf-8"):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            written.append(path)
            path.write_text(content, encoding="utf-8")
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


