"""kms SDK operations with structured AWS arguments."""
from .client import request, pages


def describe_key(context, **arguments):
    return request(context, 'kms', 'describe_key', arguments)


