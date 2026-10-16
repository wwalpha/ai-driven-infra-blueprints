#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.raw_bucket_name_reference_fixtures import *

def check_reference_schema():
    ref = {'service':'s3','resource':'017','resourceType':'S3.Bucket'}
    for spec in [{**ref,'format':'unknown'}, {**ref,'format':{}},
        {'instance':'first','resourceType':'S3.Bucket','format':'name'}]:
        rejected(lambda:reference_schema(spec),'invalid Model parameter format')
    rejected(lambda:reference_schema({**ref,'format':'name','property':'BucketName'}),'template reference requires')
    rejected(lambda:schema({'type':'string','description':'bad','required':True,'format':'name'}),'invalid Model parameter format')



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
