"""Private writable Project data populated from authored seeds."""

import shutil
from functools import partial
from pathlib import Path

import support.it_fixture_bundle as fixture_bundle


def __copy_tree_copy(src, dst):
    result = shutil.copyfile(src, dst)
    Path(dst).chmod(Path(src).stat().st_mode | 128)
    return result


def _copy_tree(seed, destination, **options):
    destination = Path(destination)
    copy = __copy_tree_copy
    shutil.copytree(seed, destination, copy_function=copy, **options)
    # copytree's directory copystat preserves readonly modes too.
    for path in [destination, *(p for p in destination.rglob("*") if p.is_dir())]:
        path.chmod(path.stat().st_mode | 0o700)
    return destination


def populate(name, destination):
    return _copy_tree(fixture_bundle.source(name), destination, dirs_exist_ok=True)


def _outside_focus(seed, paths, directory, names):
    ignored = []
    for name in names:
        candidate = (Path(directory) / name).relative_to(seed)
        if not any(
            candidate == selected
            or candidate in selected.parents
            or selected in candidate.parents
            for selected in paths
        ):
            ignored.append(name)
    return ignored


def populate_focused(name, destination, paths):
    """Copy selected seed files/trees with their parents into a private writable workspace."""
    seed = fixture_bundle.source(name)
    return _copy_tree(
        seed,
        destination,
        dirs_exist_ok=True,
        ignore=partial(_outside_focus, seed, tuple(Path(path) for path in paths)),
    )
