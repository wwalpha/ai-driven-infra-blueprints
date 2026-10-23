"""Private writable Project data populated from authored seeds."""
import shutil
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
    for path in [destination, *(p for p in destination.rglob('*') if p.is_dir())]:
        path.chmod(path.stat().st_mode | 0o700)
    return destination


def populate(name, destination):
    return _copy_tree(fixture_bundle.source(name), destination, dirs_exist_ok=True)
