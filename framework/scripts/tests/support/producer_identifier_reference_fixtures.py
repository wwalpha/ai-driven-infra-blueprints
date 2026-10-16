"""Offline raw typed identifiers: observed authority, rejection and dependency propagation."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from support.model_sources import write_model

from model_files import read_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy

import tempfile

import model_templates as t

from model_files import load_model

from model_parameter_inputs import reference_schema, schema

from support.model_sources import write_fixture_files as save_files

def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError) as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid identifier reference accepted: ' + phrase)


__all__ = ['Path', 'copy', 'load_model', 'read_model', 'reference_schema', 'rejected', 'save_files', 'schema', 'sys', 't', 'tempfile', 'write_model']
