"""Strict shared YAML reader for mappings and IaC inputs."""
import re

def yaml_read(text):
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    # YAML 1.2-like scalars: on/off/yes/no and dates stay strings; no octal surprise.
    Loader.yaml_implicit_resolvers = {
        key: [(tag, regex) for tag, regex in rules if tag not in {
            'tag:yaml.org,2002:bool', 'tag:yaml.org,2002:int', 'tag:yaml.org,2002:timestamp'}]
        for key, rules in Loader.yaml_implicit_resolvers.items()}
    Loader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false)$'), list('tf'))
    Loader.add_implicit_resolver('tag:yaml.org,2002:int', re.compile(r'^[-+]?(?:0|[1-9][0-9]*)$'), list('-+0123456789'))

    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str) or key in result:
                raise ValueError(f'non-string/duplicate YAML key: {key}')
            result[key] = loader.construct_object(value_node)
        return result

    Loader.add_constructor('tag:yaml.org,2002:map', mapping)
    try:
        return yaml.load(text, Loader=Loader)
    except yaml.YAMLError as error:
        raise ValueError(f'invalid parameters YAML: {error}') from error

