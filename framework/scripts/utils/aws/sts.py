"""sts SDK operations with structured AWS arguments."""

from .client import pages as pages
from .client import request as request


def get_caller_identity(context, **arguments):
    return request(context, "sts", "get_caller_identity", arguments)
