"""Local expression evaluation over supplied inputs and three bounded lookups.

Symbol/export lookups may load tracked local inputs; the evaluator itself does no I/O.
AWS/deploy mode deliberately retains its existing narrower evaluation contract.
"""
import re

from cloudformation_inputs import Blocked, resolve_value
from iac_values import ResourceReference, Expression, cfn_resource_identity


class Evaluation:
    def __init__(self, stack_inputs, resources, property_schema, symbol, import_value, local_comparison):
        self.stack_inputs, self.resources = stack_inputs, resources
        self.property_schema, self.symbol, self.import_value = property_schema, symbol, import_value
        self.local_comparison = local_comparison

    def string_operand(self, value):
        if isinstance(value, str):
            return True
        if isinstance(value, Expression):
            return value.operation in {'Select', 'Join', 'Sub'}
        if isinstance(value, ResourceReference):
            service, identity = value['$resource']
            kind = self.resources[service][identity]['resourceType']
            node = self.property_schema(kind, value['$attribute'])
            if 'type' not in node:
                raise Blocked('reference string type is unproven')
            return node['type'] == 'string'
        return False


    def substitution(self, stack, value, seen):
        if isinstance(value, ResourceReference):
            service, identity = value['$resource']
            attribute = value['$attribute']
            resource = self.resources[service][identity]
            if not resource.get('cfn-logicalId'):
                raise Blocked('resource substitution requires explicit cfn-logicalId')
            name, logical = cfn_resource_identity(resource['cfn-logicalId'])
            token = ('resource', name, logical, attribute)
            if token in seen:
                raise Blocked(f'cyclic resource substitution: {name}/{logical}.{attribute}')
            document, _, _ = self.stack_inputs[name]
            if document.get('Transform'):
                raise Blocked('Transform requires external evaluation')
            properties = document['Resources'][logical].get('Properties', {})
            if attribute not in properties:
                if self.string_operand(value):
                    return value
                raise Blocked(f'resource substitution has no explicit string property: {logical}.{attribute}')
            return self.substitution(name, self.evaluate(name, properties[attribute], seen | {token}), seen | {token})
        if isinstance(value, Expression) and self.string_operand(value):
            return value
        if type(value) in (int, float):
            return str(value)
        if not isinstance(value, str):
            raise Blocked('Sub variable is not a proven local string')
        return value

    def evaluate(self, stack, value, seen=frozenset()):
        document, parameters, pseudo = self.stack_inputs[stack]
        if isinstance(value, list):
            return [item for item in (self.evaluate(stack, child, seen) for child in value) if item != {'$noValue': True}]
        if not isinstance(value, dict):
            # cfn-lint attaches source marks using scalar subclasses; preserve JSON type.
            if isinstance(value, str):
                return str(value)
            if isinstance(value, bool):
                return bool(value)
            if isinstance(value, int):
                return int(value)
            if isinstance(value, float):
                return float(value)
            return value
        if isinstance(value, ResourceReference):
            return value
        if len(value) == 1:
            key, arg = next(iter(value.items()))
            if ('export-name',) in seen and (key in {'Fn::GetAtt', 'Fn::ImportValue'} or key == 'Ref' and arg not in parameters | pseudo):
                raise Blocked('Export name depends on a resource/import')
            if key == 'Ref' and arg not in parameters | pseudo:
                if arg.startswith('AWS::'):
                    raise Blocked(f'unresolved pseudo parameter: {arg}')
                return self.symbol(stack, arg)
            if key == 'Fn::GetAtt':
                logical, attribute = arg.split('.', 1) if isinstance(arg, str) else arg
                return self.symbol(stack, logical, attribute)
            if key == 'Fn::If':
                if not isinstance(arg, list) or len(arg) != 3:
                    raise ValueError('invalid Fn::If')
                condition = resolve_value({'Condition': arg[0]}, parameters, pseudo, conditions=document.get('Conditions', {}))
                return self.evaluate(stack, arg[1 if condition else 2], seen)
            if key == 'Fn::Select':
                if not isinstance(arg, list) or len(arg) != 2:
                    raise ValueError('invalid Fn::Select')
                index, items = self.evaluate(stack, arg, seen)
                if isinstance(index, str) and index.isdigit():
                    index = int(index)
                if self.local_comparison and (isinstance(index, Expression) or isinstance(index, ResourceReference)):
                    raise Blocked('Select index is unproven')
                if type(index) is not int or index < 0:
                    raise ValueError('invalid Select operands')
                if isinstance(items, Expression) and items.operation == 'Split':
                    # Split always has element zero; other bounds need a concrete string.
                    if index != 0:
                        raise Blocked('Select bounds are unproven for symbolic Split')
                    return Expression('Select', [index, items])
                if not isinstance(items, list) or index >= len(items) or items[index] is None:
                    raise ValueError('invalid Select operands')
                return items[index]
            if key == 'Fn::Split':
                if not isinstance(arg, list) or len(arg) != 2 or not isinstance(arg[0], str) or not arg[0]:
                    raise ValueError('invalid Split operands')
                delimiter, text = arg[0], self.evaluate(stack, arg[1], seen)
                if isinstance(text, str):
                    return text.split(delimiter)
                if self.local_comparison and self.string_operand(text):
                    return Expression('Split', [str(delimiter), text])
                raise ValueError('invalid Split operands')
            if key == 'Fn::FindInMap' and isinstance(arg, list) and len(arg) == 3:
                mapping, first, second = self.evaluate(stack, arg, seen)
                try:
                    return self.evaluate(stack, document['Mappings'][mapping][first][second], seen)
                except (KeyError, TypeError) as error:
                    raise Blocked('unresolved FindInMap') from error
            if key == 'Fn::ImportValue':
                if self.local_comparison:
                    return self.import_value(stack, arg, seen)
                raise Blocked('ImportValue handoff cannot be established locally')
            if key == 'Fn::Sub' and self.local_comparison:
                text, variables = (arg, {}) if isinstance(arg, str) else arg if isinstance(arg, list) and len(arg) == 2 else (None, None)
                if not isinstance(text, str) or not isinstance(variables, dict):
                    raise ValueError('invalid Fn::Sub')
                substitutions = parameters | pseudo | {key: self.evaluate(stack, child, seen) for key, child in variables.items()}
                resolved = {}
                def replace(match):
                    key = match.group(1)
                    if key.startswith('!'):
                        return '${' + key[1:] + '}'
                    if key in substitutions:
                        child = substitutions[key]
                    else:
                        child = self.evaluate(stack, {'Fn::GetAtt': key} if '.' in key else {'Ref': key}, seen)
                    child = self.substitution(stack, child, seen)
                    resolved[key] = child
                    return child if isinstance(child, str) else match.group(0)
                concrete = re.sub(r'\$\{([^}]+)\}', replace, text)
                if all(isinstance(child, str) for child in resolved.values()):
                    return concrete
                if re.fullmatch(r'\$\{([^}]+)\}', text) and len(resolved) == 1:
                    return next(iter(resolved.values()))
                return Expression('Sub', [str(text), resolved])
            if key == 'Fn::Join' and self.local_comparison:
                if not isinstance(arg, list) or len(arg) != 2 or not isinstance(arg[0], str):
                    raise ValueError('invalid Fn::Join')
                delimiter, parts = str(arg[0]), self.evaluate(stack, arg[1], seen)
                if not isinstance(parts, list):
                    raise ValueError('invalid Join operands')
                if all(isinstance(part, str) for part in parts):
                    return delimiter.join(parts)
                if not all(self.string_operand(part) for part in parts):
                    raise ValueError('invalid Join operands')
                return Expression('Join', [delimiter, parts])
            if key == 'Fn::Sub' and isinstance(arg, list):
                if len(arg) != 2 or not isinstance(arg[0], str) or not isinstance(arg[1], dict):
                    raise ValueError('invalid Fn::Sub')
                variables = {key: self.evaluate(stack, child, seen) for key, child in arg[1].items()}
                variables = {key: str(child) if type(child) in (int, float) else child for key, child in variables.items()}
                value = {'Fn::Sub': [arg[0], variables]}
            if key == 'Ref' or key.startswith('Fn::') or key == 'Condition':
                return resolve_value(value, {k: str(v) if type(v) in (int, float) else v for k, v in parameters.items()} if key == 'Fn::Sub' else parameters, pseudo, conditions=document.get('Conditions', {}))
        return {key: item for key, item in ((key, self.evaluate(stack, child, seen)) for key, child in value.items()) if item != {'$noValue': True}}

