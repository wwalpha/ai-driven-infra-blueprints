"""Private signed Import receipts; independent of Model/validation runtime."""
import hmac
import json
import os
import secrets
from pathlib import Path

from task_contract_core import TASK_NAME

from utils.file_operations import atomic_files, evidence_store
from utils.json_format import json_text


def seal_key(root):
    path = evidence_store(root) / 'seal.key'
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = None
    if descriptor is not None:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(secrets.token_bytes(32))
    if path.is_symlink() or not path.is_file() or (os.name != 'nt' and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077)):
        raise ValueError('IMPORT unsafe local evidence seal')
    value = path.read_bytes()
    if len(value) != 32:
        raise ValueError('IMPORT invalid local evidence seal')
    return value

def sealed(root, value, *, key_for=seal_key):
    payload = json_text(value)
    return json_text({'payload': value, 'signature': hmac.new(key_for(root), payload.encode('utf-8'), 'sha256').hexdigest()}) + '\n'

def read_sealed(root, file, *, key_for=seal_key):
    if file.is_symlink():
        raise ValueError('IMPORT symlink evidence is forbidden')
    envelope = json.loads(file.read_text(encoding='utf-8'))
    if set(envelope) != {'payload', 'signature'} or not isinstance(envelope['signature'], str):
        raise ValueError('IMPORT invalid sealed evidence')
    expected = hmac.new(key_for(root), json_text(envelope['payload']).encode('utf-8'), 'sha256').hexdigest()
    if not hmac.compare_digest(expected, envelope['signature']):
        raise ValueError('IMPORT acquisition evidence was modified')
    return envelope['payload']

def write_sealed(root, file, value, *, encode=sealed):
    atomic_files({file: encode(root, value)}, staging_directory=file.parent)

def discard_import_proof(root, task_name):
    """Remove only this task's sealed receipt after verified integration/snapshot use."""
    if not TASK_NAME.fullmatch(task_name):
        raise ValueError('invalid evidence task identity')
    file = evidence_store(root, create=False) / (Path(task_name).stem + '.json')
    if file.exists() or file.is_symlink():
        proof = read_sealed(root, file)
        if proof.get('task') != task_name:
            raise ValueError('IMPORT evidence belongs to another task')
        file.unlink()
