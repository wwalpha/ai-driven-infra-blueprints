"""sts SDK operations with structured AWS arguments."""
from .client import request, pages


def get_caller_identity(context, **arguments):
    return request(context, 'sts', 'get_caller_identity', arguments)


