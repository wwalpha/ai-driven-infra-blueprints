"""Fixed dynamodb design definitions; no display-engine dependencies."""

POLICY_FORMATS = {
    "DynamoDB.GlobalTable.Replicas[].ReplicaStreamSpecification.ResourcePolicy.PolicyDocument": "statement",
    "DynamoDB.GlobalTable.Replicas[].ResourcePolicy.PolicyDocument": "statement",
    "DynamoDB.Table.ResourcePolicy": "wrapped-statement",
    "DynamoDB.Table.StreamSpecification.ResourcePolicy.PolicyDocument": "statement",
}
