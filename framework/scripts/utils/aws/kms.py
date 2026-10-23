"""kms SDK operations with structured AWS arguments."""
from .client import pages as pages
from .client import request as request


def describe_key(context, **arguments):
    return request(context, 'kms', 'describe_key', arguments)
