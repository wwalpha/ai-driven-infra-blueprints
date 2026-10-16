"""Offline raw BucketName JSON and unchanged link reference regression."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy

import json

from support.model_sources import write_model, write_fixture_files

import tempfile

import model_templates as t

from model_files import load_model

from model_parameter_inputs import reference_schema, schema

from support.model_sources import write_fixture_files as save_files

def rejected(call, phrase):
    try:
        call()
    except (ValueError, OSError) as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid reference accepted: '+phrase)


__all__ = ['Path', 'copy', 'json', 'load_model', 'reference_schema', 'rejected', 'save_files', 'schema', 'sys', 't', 'tempfile', 'write_fixture_files', 'write_model']
