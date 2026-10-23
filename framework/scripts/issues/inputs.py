"""Saved View review diagnostics; comparison inputs own only their byte observations."""
import hashlib
from comparison.inputs import Inputs

def view_text(self, path, *, phase):
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        Inputs.retain_hash(self, path, None)
        return None
    except OSError as error:
        self.unreadable_inputs = True
        raw = None
        failure = error
    else:
        Inputs.retain_hash(self, path, hashlib.sha256(raw).hexdigest())
        try:
            return raw.decode('utf-8')
        except UnicodeError as error:
            failure = error
    self.view_errors[path] = dict(code='mechanical.view_read', service=path.stem,
        path=path.relative_to(self.root).as_posix(), phase=phase, exception=type(failure).__name__,
        message='saved View could not be read; dependent checks not run')
    return None
