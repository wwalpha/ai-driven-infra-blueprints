"""Build explicit properties authorities from authored synthetic test values."""

from contextlib import contextmanager
from dataclasses import replace
from functools import partial as _bind_framework_callback
from unittest.mock import patch

import aws_mapping_display as _imports_aws_mapping_display
import design_layout as _imports_design_layout
import model.identity as _imports_model_identity
import model.projection as _imports_model_projection
import validation_cache as _imports_validation_cache
from model.core import properties
from model.format import FORMAT, INDEX, split, strict_json
from model.sources import load_model, model_parts, scope_for
from sync_files import save_files


def write_model(path, values):
    """Fixture initialization only; production writes use the Task save capability."""
    path = path.absolute()
    scope_for(path)
    comments = []
    if isinstance(values, str):
        comments = [line for line in values.splitlines() if line.startswith('#') and not line.startswith(
            ('# Generated', '# Authoritative', '# model-format:', '# model-index:', '# part:'))]
        try:
            values = properties(values)
        except ValueError:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(FORMAT + '\n' + values, encoding='utf-8')
            return path
    values = dict(values)
    for key, value in list(values.items()):
        if key.startswith('observed.row.') and key.endswith(('.property', '.comment')) and values.get(
                key.replace('observed.', 'desired.', 1)) == value:
            del values[key]
        elif key.endswith('.artifactSha256'):
            document_sha256 = _imports_model_projection.document_sha256
            document = values.get(key.removesuffix('artifactSha256') + 'document')
            try:
                if document is not None and document_sha256(strict_json(document)) == value:
                    del values[key]
            except ValueError:
                pass  # Keep malformed negative fixture values for the production reader.
    for key, value in list(values.items()):
        if key.startswith('desired.stack.') and key.endswith('.name'):
            values.setdefault(key.removesuffix('name') + 'placementName', value)
    previous = set(model_parts(path)) if path.is_file() else set()
    output = split(path, values)
    if comments:
        first = next(file for file in output if file != path) if output[path].splitlines()[1:2] == [INDEX] else path
        output[first] = output[first] + '\n'.join(comments) + '\n'
    save_files(output)
    for obsolete in previous - output.keys():
        obsolete.unlink()
    return path


def write_fixture_files(output):
    """Initialize only explicitly supplied service entries; never discover executing inputs."""
    output = dict(output)
    for path, text in list(output.items()):
        if len(path.parents) < 4 or path.parents[2].name != 'model' or path.suffix != '.properties':
            continue
        if text.startswith(FORMAT + '\n' + INDEX):
            parts = [path.parent / line.removeprefix('# part: ') for line in text.splitlines() if line.startswith('# part: ')]
            text = FORMAT + '\n' + ''.join(output[part].removeprefix(FORMAT + '\n') for part in parts)
        write_model(path, text)
        for existing in list(output):
            if existing == path or existing.parent == path.with_suffix(''):
                del output[existing]
    save_files(output)


def snapshot_model(path):
    return {file: file.read_bytes() for file in load_model(path).files}


def _callback_catalog_display_selectable(HIDDEN_PROPERTIES, original, /, root, kind):
    return {key: replace(prop, include=True, show=key not in HIDDEN_PROPERTIES)
            for key, prop in original(root, kind).items()}


@contextmanager
def catalog_display():
    """Legacy catalog fixtures select all fields, independent of consumer display sets."""

    aws_mapping_display = _imports_aws_mapping_display
    HIDDEN_PROPERTIES = _imports_design_layout.HIDDEN_PROPERTIES
    memoized = _imports_validation_cache.memoized
    original = aws_mapping_display.rules

    selectable = (memoized)(_bind_framework_callback(_callback_catalog_display_selectable, HIDDEN_PROPERTIES, original))

    with patch.object(aws_mapping_display, 'rules', selectable):
        yield


def allocate_fixture(values, resource_ids):
    """Author fixed anchors when explicitly allocating synthetic test resources."""
    allocate = _imports_model_identity.allocate
    result = allocate(values, resource_ids)
    for number in resource_ids:
        key = f'desired.resource.{number}.'
        result.setdefault(key + 'anchor', 'resource-' + result[key + 'logicalId'])
    return result
