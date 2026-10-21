#!/usr/bin/env python3
"""Offline static-definition lifetimes; synthetic roots, no consumer Models."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch
import os
import shutil
import socket

import aws_mapping
import aws_mapping_catalog
from utils.aws_catalogs import Catalogs
from utils.aws_mappings import Mappings, mapping_alias
from utils.aws_schemas import Schemas
from utils.aws_sdk import Sdk, sdk_for
from validation_cache import input_scope
from support.aws_mapping_fixtures import mapping_fixture


def parallel(obtain):
    barrier = Barrier(8)
    def run(_):
        barrier.wait(timeout=10)
        return obtain()
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(run, range(8)))


def check_sdk_lifetime():
    session = Mock()
    session.get_service_model.side_effect = lambda service: SimpleNamespace(service=service)
    factory = Mock(return_value=session)
    with patch.dict(os.environ, {'AWS_DATA_PATH': 'first'}):
        sdk = Sdk(factory)
    assert factory.call_count == 0
    with patch.dict(os.environ, {'AWS_DATA_PATH': 'later'}):
        results = parallel(lambda: sdk.service_model('sns'))
    assert all(value is results[0] for value in results)
    assert factory.call_count == session.get_service_model.call_count == 1
    session.set_config_variable.assert_called_once_with('data_path', 'first')
    assert sdk.service_model('sqs').service == 'sqs'
    assert session.get_service_model.call_count == 2
    other = Sdk(factory)
    assert other.service_model('sns') is not results[0]
    assert factory.call_count == 2
    with TemporaryDirectory() as directory:
        first = sdk_for(Path(directory) / 'first')
        assert first is sdk_for(Path(directory) / 'first')
        assert first is not sdk_for(Path(directory) / 'second')


def check_failure_waiters():
    class Interrupted(BaseException):
        pass
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory), 'config')
        schemas, catalogs = Schemas(root), Catalogs(root)
        error = Interrupted('injected cancellation')
        factory = Mock(side_effect=error)
        sdk = Sdk(factory)
        original = Path.read_text
        reads = Counter()
        def read(path, *args, **kwargs):
            reads[path.name] += 1
            if path.name in {'aws-config-configurationrecorder.json', 'Config_ConfigurationRecorder.properties'}:
                raise error
            return original(path, *args, **kwargs)
        def fails(obtain):
            def request():
                try:
                    obtain()
                except BaseException as caught:
                    return caught
                raise AssertionError('failure was suppressed')
            assert all(value is error for value in parallel(request))
            assert request() is error
        with patch.object(Path, 'read_text', read):
            fails(lambda: schemas.cloudformation('AWS::Config::ConfigurationRecorder'))
            fails(lambda: catalogs.selected('Config.ConfigurationRecorder'))
            fails(lambda: sdk.service_model('sns'))
        assert reads == {'index.json': 1, 'aws-config-configurationrecorder.json': 1, 'Config_ConfigurationRecorder.properties': 1}
        assert factory.call_count == 1
        # New instances can retry independent read failures; no error-cache invalidation scans.
        assert Schemas(root).cloudformation('AWS::Config::ConfigurationRecorder')['typeName'] == 'AWS::Config::ConfigurationRecorder'
        assert 'Name' in Catalogs(root).selected('Config.ConfigurationRecorder')


def check_full_validation_dependencies():
    with TemporaryDirectory() as directory:
        root = mapping_fixture(Path(directory) / 'root', 'sns', 'config')
        provider = Mappings(root)
        sdk, schemas, catalogs = Sdk(), Schemas(root), Catalogs(root)
        with patch('utils.aws_sdk.sdk_for', side_effect=AssertionError('runtime initialized SDK')), \
             patch('utils.aws_schemas.schemas_for', side_effect=AssertionError('runtime initialized schemas')), \
             patch('utils.aws_catalogs.catalogs_for', side_effect=AssertionError('runtime initialized catalogs')):
            assert provider.get('config').service == 'config'
        with patch.object(aws_mapping_catalog, 'catalog_properties', wraps=aws_mapping_catalog.catalog_properties) as validate:
            def obtain():
                return provider.validated('sns', sdk, schemas, catalogs, validate)
            results = parallel(obtain)
            assert all(value is results[0] for value in results)
            assert validate.call_count == 1
            assert input_scope(obtain)() is input_scope(obtain)()
            assert validate.call_count == 1
            for deps in ((Sdk(), schemas, catalogs), (sdk, Schemas(root), catalogs), (sdk, schemas, Catalogs(root))):
                assert provider.validated('sns', *deps, validate).properties == results[0].properties
            assert validate.call_count == 4
            Mappings(root).validated('sns', sdk, schemas, catalogs, validate)
            assert validate.call_count == 5
            provider.validated('config', sdk, schemas, catalogs, validate)
            assert validate.call_count == 6
            # Validation/adapter implementation edits require a new lifetime as well.
            replacement = Mock(wraps=aws_mapping_catalog.catalog_properties)
            provider.validated('sns', sdk, schemas, catalogs, replacement)
            assert replacement.call_count == 1
        failure = ValueError('invalid static mapping')
        invalid = Mock(side_effect=failure)
        def failed():
            try:
                provider.validated('sns', sdk, schemas, catalogs, invalid)
            except ValueError as caught:
                return caught
            raise AssertionError('full validation failure accepted')
        assert all(value is failure for value in parallel(failed))
        assert invalid.call_count == 1
        assert provider.get('sns').service == 'sns'


def check_stage_survival_and_definition_sources():
    with TemporaryDirectory() as directory:
        mapping_root = mapping_fixture(Path(directory) / 'mapping', 'config')
        short = Path(directory) / 'short'
        short.mkdir()
        with patch.object(aws_mapping_catalog, 'catalog_properties', wraps=aws_mapping_catalog.catalog_properties) as validate:
            with mapping_alias(mapping_root, short):
                staged = aws_mapping.registry(short, 'config')
                assert staged.root == short
            shutil.rmtree(short)
            source = aws_mapping.registry(mapping_root, 'config')
            assert source.root == mapping_root
            assert source.properties is staged.properties
            assert validate.call_count == 1


if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        check_sdk_lifetime()
        check_failure_waiters()
        check_full_validation_dependencies()
        check_stage_survival_and_definition_sources()
    print('Static AWS definitions: PASS (SDK lifetime, independent read failures, Mapping dependencies, stage survival)')
