"""s3 SDK operations with structured AWS arguments."""

from .client import pages as pages
from .client import request as request


def head_bucket(context, **arguments):
    return request(context, "s3", "head_bucket", arguments)


def get_bucket_location(context, **arguments):
    return request(context, "s3", "get_bucket_location", arguments)


def get_bucket_encryption(context, **arguments):
    return request(context, "s3", "get_bucket_encryption", arguments)


def get_bucket_policy(context, **arguments):
    return request(context, "s3", "get_bucket_policy", arguments)


def head_object(context, **arguments):
    return request(context, "s3", "head_object", arguments)


def put_object(context, **arguments):
    return request(context, "s3", "put_object", arguments)
