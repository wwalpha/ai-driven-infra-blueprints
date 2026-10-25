"""Optional SDK integration; loaded only when an AWS/SDK capability is requested."""

import boto3
import botocore.config as config
import botocore.loaders as loaders
import botocore.session as session
from botocore import xform_name
from botocore.exceptions import BotoCoreError as BotoCoreError
from botocore.exceptions import ClientError as ClientError
from botocore.exceptions import UnknownRegionError as UnknownRegionError


def sdk_session():
    return session.get_session()


def sdk_config(**options):
    return config.Config(**options)


def sdk_loader():
    return loaders.Loader()


def connection_session(profile, region):
    return boto3.Session(profile_name=profile, region_name=region)


def operation_name(model, operation):
    return next(
        (name for name in model.operation_names if xform_name(name) == operation), None
    )
