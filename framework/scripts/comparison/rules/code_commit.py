"""Static CodeCommit comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "CodeCommit.Repository": properties(
        objects="""
            Code
            Code.S3
            Tags[]
            Triggers[]
        """,
        ordered="""
            Triggers
            Triggers[].Branches
            Triggers[].Events
        """,
        references="""
            KmsKeyId
        """,
        scalars="""
            Code.BranchName
            Code.S3.Bucket
            Code.S3.Key
            Code.S3.ObjectVersion
            RepositoryDescription
            RepositoryName
            Tags[].Key
            Tags[].Value
            Triggers[].CustomData
            Triggers[].DestinationArn
            Triggers[].Name
        """,
        tags="""
            Tags
        """,
    ),
}
