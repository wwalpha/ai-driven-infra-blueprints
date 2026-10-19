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
import json
import os
import shutil
import socket

import aws_mapping
import aws_mapping_catalog
from design_catalog import DesignSchemaCatalog, selected_properties
from design_layout import catalog_property_order
from model_references import catalog_outputs
from utils.aws_catalogs import Catalogs, catalogs_for
from utils.aws_mappings import Mappings, mapping_alias
from utils.aws_schemas import Schemas, schemas_for
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


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')
    return path


def fixture(root):
    directory = 'framework/materials/cloudformation-schema/ap-northeast-1/'
    write(root, directory + 'index.json', json.dumps({'resourceTypes': {
        'AWS::Test::One': 'one.json', 'AWS::Test::Two': 'two.json'}}))
    for kind in ('One', 'Two'):
        write(root, directory + kind.lower() + '.json', json.dumps({
            'typeName': 'AWS::Test::' + kind, 'properties': {'Name': {'type': 'string'}, 'Id': {'type': 'string'}}}))
        write(root, 'framework/materials/aws/Test_' + kind + '.properties',
              'Test.' + kind + '.Name=\nTest.' + kind + '.Id=IDENTIFIER_OUTPUT\n')
        write(root, 'framework/materials/api/Api_' + kind + '.json', json.dumps({
            'properties': {'Value': {'type': 'array', 'items': {'type': 'string'}}}}))
    return root


def check_lazy_parallel_and_mutation():
    with TemporaryDirectory() as directory:
        root = fixture(Path(directory))
        reads = Counter()
        original = Path.read_text
        def read(path, *args, **kwargs):
            reads[path.name] += 1
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            schemas, catalogs = schemas_for(root), catalogs_for(root)
            assert not reads
            assert len(schemas.api_paths) == 2
            assert len(catalogs.paths) == 2
            assert not reads
            assert all(value is schemas for value in parallel(lambda: schemas_for(root)))
            assert all(value is catalogs for value in parallel(lambda: catalogs_for(root)))
            facades = parallel(lambda: DesignSchemaCatalog(root))
            assert reads == {'index.json': 1}
            assert all('Api.One' in facade.api_schemas for facade in facades)
            assert not any(name.startswith('Api_') for name in reads)
            documents = parallel(lambda: schemas.cloudformation('AWS::Test::One'))
            assert all(value is documents[0] for value in documents)
            api = parallel(lambda: schemas.api('Api.One'))
            assert all(value is api[0] for value in api)
            selections = parallel(lambda: catalogs.selected('Test.One'))
            assert all(value is selections[0] for value in selections)
            assert catalogs.order('Test.One')['Test.One.Id'] == 1
            assert catalogs.outputs('Test.One') == {'Test.One.Id'}
            assert reads == {'index.json': 1, 'one.json': 1, 'Api_One.json': 1, 'Test_One.properties': 1}
            @input_scope
            def scoped():
                assert selected_properties(root, 'Test.One') == {'Name', 'Id'}
                assert catalog_property_order(root, 'Test.One')['Test.One.Id'] == 1
                assert catalog_outputs(root, 'Test.One') == {'Test.One.Id'}
                return DesignSchemaCatalog(root).schema('Test.One')
            assert scoped() == scoped()
            assert reads['one.json'] == reads['Test_One.properties'] == 1
            # Public mutable schema views are isolated once per catalog/resource.
            first, other = facades[:2]
            first.schema('Test.One')['properties']['Name']['type'] = 'integer'
            first.api_schemas['Api.One']['properties']['Value']['items']['type'] = 'integer'
            first.resource_types.clear()
            assert other.schema('Test.One')['properties']['Name']['type'] == 'string'
            assert other.api_schemas['Api.One']['properties']['Value']['items']['type'] == 'string'
            assert isinstance(other.schema('Test.One'), dict)
            assert isinstance(other.api_schemas['Api.One']['properties']['Value'], dict)
            assert other.schema('Test.One') is other.schema('Test.One')
            order = catalog_property_order(root, 'Test.One')
            order.clear()
            assert catalog_property_order(root, 'Test.One')['Test.One.Id'] == 1
            outputs = catalog_outputs(root, 'Test.One')
            outputs.clear()
            assert catalog_outputs(root, 'Test.One') == {'Test.One.Id'}
            indexes = parallel(catalogs.design_properties)
            assert all(value is indexes[0] for value in indexes)
            assert indexes[0][1]['Name'] == {'Test.One', 'Test.Two'}
            assert reads['Test_Two.properties'] == 1
            assert 'two.json' not in reads and 'Api_Two.json' not in reads


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
        root = fixture(Path(directory))
        schemas, catalogs = Schemas(root), Catalogs(root)
        error = Interrupted('injected cancellation')
        factory = Mock(side_effect=error)
        sdk = Sdk(factory)
        original = Path.read_text
        reads = Counter()
        def read(path, *args, **kwargs):
            reads[path.name] += 1
            if path.name in {'one.json', 'Test_One.properties'}:
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
            fails(lambda: schemas.cloudformation('AWS::Test::One'))
            fails(lambda: catalogs.selected('Test.One'))
            fails(lambda: sdk.service_model('sns'))
        assert reads == {'index.json': 1, 'one.json': 1, 'Test_One.properties': 1}
        assert factory.call_count == 1
        # New instances can read repaired definitions; no error-cache invalidation scans.
        assert Schemas(root).cloudformation('AWS::Test::One')['typeName'] == 'AWS::Test::One'
        assert Catalogs(root).selected('Test.One') == {'Id', 'Name'}


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
        # File changes cannot silently alter an existing provider, but fresh ones validate them.
        path = root / 'framework/mappings/aws/sns.yaml'
        document = aws_mapping.yaml_read(path.read_text(encoding='utf-8'))
        document['version'] = 2
        import yaml
        path.write_text(yaml.safe_dump(document), encoding='utf-8')
        assert obtain().properties == results[0].properties
        try:
            Mappings(root).validated('sns', Sdk(), Schemas(root), Catalogs(root), aws_mapping_catalog.catalog_properties)
        except ValueError as error:
            assert 'version' in str(error)
        else:
            raise AssertionError('changed Mapping was not validated')


def check_stage_survival_and_definition_sources():
    with TemporaryDirectory() as directory:
        root = fixture(Path(directory) / 'source')
        from design_layout import HIDDEN_PROPERTIES
        hidden = next(iter(HIDDEN_PROPERTIES))
        write(root, 'framework/materials/api/Api_One.properties',
              'Api.One.Id=IDENTIFIER_OUTPUT\n' + hidden + '=IDENTIFIER_OUTPUT\n')
        assert catalog_outputs(root, 'Api.One') == {'Api.One.Id'}
        assert catalogs_for(root).lines('Absent.Resource') is None
        # Alias registration reuses the existing Mapping provider's source identity.
        write(root, 'framework/mappings/aws/owners.json', '{"Test.One":"test"}')
        stage = Path(directory) / 'stage'
        stage.mkdir()
        with mapping_alias(root, stage):
            schemas, catalogs, sdk = schemas_for(stage), catalogs_for(stage), sdk_for(stage)
            assert schemas is schemas_for(root) and catalogs is catalogs_for(root) and sdk is sdk_for(root)
            assert schemas.root == catalogs.root == root
            assert DesignSchemaCatalog(stage).root == stage
            assert catalogs.selected('Test.One') == {'Name', 'Id'}
        shutil.rmtree(stage)
        assert schemas.cloudformation('AWS::Test::Two')['typeName'] == 'AWS::Test::Two'
        assert schemas.api('Api.Two')['properties']['Value']['type'] == 'array'
        assert catalogs.selected('Test.Two') == {'Name', 'Id'}
        other = fixture(Path(directory) / 'other')
        write(other, 'framework/materials/cloudformation-schema/ap-northeast-1/two.json', '{"properties":{}}')
        assert schemas_for(other) is not schemas and catalogs_for(other) is not catalogs
        assert 'typeName' not in schemas_for(other).cloudformation('AWS::Test::Two')
        # Explicit fresh instances observe edits, preserving the old static snapshot.
        write(root, 'framework/materials/cloudformation-schema/ap-northeast-1/two.json', '{"properties":{}}')
        write(root, 'framework/materials/aws/Test_Two.properties', 'Test.Two.Changed=\n')
        assert schemas.cloudformation('AWS::Test::Two')['typeName']
        assert 'typeName' not in Schemas(root).cloudformation('AWS::Test::Two')
        assert catalogs.selected('Test.Two') == {'Name', 'Id'}
        assert Catalogs(root).selected('Test.Two') == {'Changed'}
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
        check_lazy_parallel_and_mutation()
        check_sdk_lifetime()
        check_failure_waiters()
        check_full_validation_dependencies()
        check_stage_survival_and_definition_sources()
    print('Static AWS definitions: PASS (lazy/parallel/errors/lifetimes/dependencies/stages/isolation)')
