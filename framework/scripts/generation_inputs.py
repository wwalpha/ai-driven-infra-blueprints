"""Shared invocation input recorder for byte, existence, kind and file-set guards."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from task_contract import task_path
from utils.aws_mappings import definition_root, mapping_alias

class GenerationInputs:
    """Invocation-owned record of consumed raw bytes, kinds and selections."""
    def __init__(self, root, definitions_root=None, *, task_file=None):
        self.root = root
        self.runtime_root = Path(__file__).resolve().parents[2]
        self.definitions_root = definitions_root or definition_root(root)
        self.contents = {}
        self.kinds = {}
        self.selections = {}
        self.conflicts = set()
        self.sealed = False
        self.lifetime = ExitStack()
        self.stage = None
        selected_task = task_path(root, selected=task_file, required=False)
        raw_task = self.read(selected_task) if selected_task is not None else None
        self.expected_task = (None if selected_task is None else selected_task.relative_to(root).as_posix(),
                              None if raw_task is None else raw_task.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n'))
        from task_contract import status
        name, text = self.expected_task
        if text is not None and status(text) != 'running':
            raise ValueError('completed task cannot write')

    def tracks(self, path):
        if self.stage is not None and path.is_relative_to(self.stage):
            return False
        return path.is_relative_to(self.root) or path.is_relative_to(self.definitions_root) or path.is_relative_to(self.runtime_root / 'framework')

    def require_open(self, path):
        if self.sealed:
            raise ValueError(f'new generation dependency after seal: {path}')

    @staticmethod
    def live_kind(path):
        return ('symlink' if path.is_symlink() else 'file' if path.is_file() else
                'dir' if path.is_dir() else 'missing')

    def kind(self, path):
        path = Path(path)
        if path not in self.kinds:
            self.require_open(path)
            self.kinds[path] = self.live_kind(path)
            for parent in path.parents:
                if not self.tracks(parent):
                    break
                if parent not in self.kinds:
                    self.kinds[parent] = self.live_kind(parent)
        return self.kinds[path]

    def record(self, path, content):
        path = Path(path)
        if path in self.contents:
            if self.contents[path] != content:
                self.conflicts.add(path)
                raise ValueError(f'generation inputs changed while reading: {path}')
        else:
            self.require_open(path)
            self.kind(path)
            self.contents[path] = content
        return content

    def read(self, path):
        path = Path(path)
        if path not in self.contents:
            kind = self.kind(path)
            if kind not in {'file', 'missing'}:
                raise ValueError(f'unsafe generation input ({kind}): {path}')
            self.record(path, path.read_bytes() if kind == 'file' else None)
        return self.contents[path]

    @staticmethod
    def live_select(base, pattern, recursive, kinds):
        paths = base.rglob(pattern) if recursive else base.glob(pattern)
        return tuple(sorted(p for p in paths if not (p.suffix == '.pyc' and '__pycache__' in p.parts)
                            and (kinds is None or GenerationInputs.live_kind(p) in kinds)))

    def select(self, base, pattern='*', recursive=False, kinds=None):
        key = (Path(base), pattern, recursive, None if kinds is None else tuple(sorted(kinds)))
        if key not in self.selections:
            self.require_open(base)
            self.selections[key] = self.live_select(*key)
        return self.selections[key]

    def open_stage(self):
        if self.stage is None:
            self.stage = Path(self.lifetime.enter_context(tempfile.TemporaryDirectory())).resolve()
            self.lifetime.enter_context(mapping_alias(self.definitions_root, self.stage))
        return self.stage

    def copy_to_stage(self, paths):
        stage = self.open_stage()
        for path in paths:
            if not path.is_relative_to(self.root) or path.is_relative_to(self.root / 'framework'):
                raise ValueError(f'not a project stage dependency: {path}')
            data = self.read(path)
            if data is not None:
                staged = stage / path.relative_to(self.root)
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(data)

    def seal(self):
        self.sealed = True

    def close(self):
        self.lifetime.close()

    def verify(self):
        """Exactly one live comparison, before any service saves."""
        changed = self.conflicts | {p for p, data in self.contents.items()
                   if (p.read_bytes() if p.is_file() else None) != data}
        changed.update(p for p, kind in self.kinds.items() if self.live_kind(p) != kind)
        for selection, paths in self.selections.items():
            changed.update(set(self.live_select(*selection)) ^ set(paths))
        if changed:
            raise ValueError('generation inputs changed before publication: ' +
                             ', '.join(str(p.relative_to(self.root)) if p.is_relative_to(self.root) else str(p) for p in sorted(changed)))
