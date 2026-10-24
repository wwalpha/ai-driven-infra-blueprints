"""Common CFn parsing, source locations and source-span repair."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import datetime

import pytest
import yaml
from utils.cloudformation.format import decode, decode_file

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_scalars_and_intrinsics(tmp_path):
    source = '''Resources:
  Item:
    Type: AWS::S3::Bucket
    Properties:
      Name: !Sub ["${Prefix}-${Name}", {Name: !Ref Param}]
      Attribute: !GetAtt Resource.Attribute.With.Dot
      Long: {Fn::GetAtt: [Resource, Attribute.With.Dot]}
      Condition: !Condition Enabled
      Text: |
        hello
        world
      Yes: yes
      Number: 0123
      Decimal: 08
      Date: 2026-10-22
      Quoted: 'true'
'''
    locations = {}
    document, errors = decode(source.encode(), 'fixture.yaml', locations=locations)
    assert not errors
    values = document['Resources']['Item']['Properties']
    assert type(document) is dict and type(values['Name']['Fn::Sub']) is list
    assert locations[id(values)]['Name'] == source.splitlines().index('      Name: !Sub ["${Prefix}-${Name}", {Name: !Ref Param}]') + 1
    assert values['Attribute'] == values['Long'] == {'Fn::GetAtt': ['Resource', 'Attribute.With.Dot']}
    assert values['Name']['Fn::Sub'][1]['Name'] == {'Ref': 'Param'}
    assert values['Condition'] == {'Condition': 'Enabled'}
    assert values[True] is True and values['Number'] == 83 and values['Decimal'] == '08'
    assert values['Date'] == datetime.date(2026, 10, 22) and values['Quoted'] == 'true'
    assert values['Text'] == 'hello\nworld\n'
    path = tmp_path / 'input.yaml'
    path.write_text(source)
    assert decode_file(path) == (document, [])
    assert decode('{"a":[true,1,null,"x"]}')[0] == {'a': [True, 1, None, 'x']}
    assert yaml.safe_load('a: yes')['a'] is True
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load('a: !Ref X')


@pytest.mark.parametrize('text', ['a: 1\na: 2\n', 'a: [invalid', '{"a":1,"a":2}', 'a: &a [*a]'])
def check_parse_errors(text):
    document, errors = decode(text, 'bad-template.yaml')
    assert document is None and errors and 'bad-template.yaml' in errors[0]


def check_merge_and_repair():
    original = '''Defaults: &settings {Enabled: true, Count: 1}
Merged: {<<: *settings, Count: 2}
Resources:
  Item:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: old # selected
      Tags: [{Key: Owner, Value: !Ref Owner}]
'''
    document, errors = decode(original)
    assert not errors and document['Merged'] == {'Enabled': True, 'Count': 2}
    # Effective-input identity uses this existing decoder; comments cannot buy a retry.
    assert decode(original + '# formatting only\n') == (document, [])
    assert document['Resources']['Item']['Properties']['Tags'] == [{'Key': 'Owner', 'Value': {'Ref': 'Owner'}}]


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
