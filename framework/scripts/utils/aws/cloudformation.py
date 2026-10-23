"""cloudformation SDK operations with structured AWS arguments."""
from .client import pages, request


def get_template(context, **arguments):
    return request(context, 'cloudformation', 'get_template', arguments)


def describe_stacks(context, **arguments):
    return request(context, 'cloudformation', 'describe_stacks', arguments)


def list_stack_resources(context, **arguments):
    return pages(context, 'cloudformation', 'list_stack_resources', 'StackResourceSummaries', arguments)


def describe_stack_events(context, **arguments):
    return pages(context, 'cloudformation', 'describe_stack_events', 'StackEvents', arguments)


def describe_change_set(context, **arguments):
    return pages(context, 'cloudformation', 'describe_change_set', 'Changes', arguments)


def list_exports(context, **arguments):
    return pages(context, 'cloudformation', 'list_exports', 'Exports', arguments)


def validate_template(context, **arguments):
    return request(context, 'cloudformation', 'validate_template', arguments)


def create_change_set(context, **arguments):
    return request(context, 'cloudformation', 'create_change_set', arguments)


def execute_change_set(context, **arguments):
    return request(context, 'cloudformation', 'execute_change_set', arguments)


def delete_stack(context, **arguments):
    return request(context, 'cloudformation', 'delete_stack', arguments)
