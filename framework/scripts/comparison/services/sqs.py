"""sqs comparison contracts and projections."""

REF_ATTRIBUTES = {'SQS.Queue': 'QueueUrl'}

NAMED_ARN = ('QueueName', r'(?=.{1,80}$)[A-Za-z0-9_-]+(?:\.fifo)?', 'sqs', '', '')
