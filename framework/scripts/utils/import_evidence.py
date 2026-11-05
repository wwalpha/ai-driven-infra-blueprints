"""Import receipt cleanup after verified integration or snapshot use."""

from pathlib import Path

from task_contract_core import TASK_NAME

from utils.local_evidence import read_sealed
from utils.local_evidence import shared_store as evidence_store


def discard_import_proof(root, task_name):
    """Remove only this task's receipt after verified integration/snapshot use."""
    if not TASK_NAME.fullmatch(task_name):
        raise ValueError("invalid evidence task identity")
    file = evidence_store(root, create=False) / (Path(task_name).stem + ".json")
    if file.exists() or file.is_symlink():
        proof = read_sealed(root, file)
        if proof.get("task") != task_name:
            raise ValueError("IMPORT evidence belongs to another task")
        file.unlink()
