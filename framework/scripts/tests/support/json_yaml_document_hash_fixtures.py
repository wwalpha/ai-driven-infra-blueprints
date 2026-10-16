"""YAML document digests, input contracts and offline updates."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy

import hashlib

import tempfile

import model_templates as t

from model_files import load_model

from model_projection import document_sha256, json_sha256

from model_parameter_inputs import parameter_text

from support.model_sources import write_fixture_files as save_files


__all__ = ['Path', 'copy', 'document_sha256', 'hashlib', 'json_sha256', 'load_model', 'parameter_text', 'save_files', 'sys', 't', 'tempfile']
