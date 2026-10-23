"""s3 comparison contracts and projections."""

import re

from cloudformation_inputs import Blocked

REF_ATTRIBUTES = {'S3.Bucket': 'BucketName'}



SUB_ARN_KINDS = {'S3.Bucket'}

def literal_arn(bucket, pseudo, mode):
    if mode == 'IMPORT':
        raise Blocked('S3 ARN requires a CREATE resource with an explicit BucketName')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
        raise Blocked('S3 ARN requires a proven bucket name without a path or wildcard')
    return f"arn:{pseudo['AWS::Partition']}:s3:::{bucket}"

DESIGN_ONLY = {('S3.Bucket', 'Region')}
