"""Static Events comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "Events.EventBus": properties(
        objects="""
            DeadLetterConfig
            LogConfig
            Policy
            Tags[]
        """,
        scalars="""
            DeadLetterConfig.Arn
            Description
            EventSourceName
            KmsKeyIdentifier
            LogConfig.IncludeDetail
            LogConfig.Level
            Name
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "Events.Rule": properties(
        objects="""
            EventPattern
            Tags[]
            Targets[]
            Targets[].DeadLetterConfig
            Targets[].HttpParameters
            Targets[].HttpParameters.HeaderParameters
            Targets[].HttpParameters.QueryStringParameters
            Targets[].InputTransformer
            Targets[].InputTransformer.InputPathsMap
            Targets[].RetryPolicy
        """,
        ordered="""
            Targets
            Targets[].HttpParameters.PathParameterValues
        """,
        scalars="""
            Description
            EventBusName
            Name
            RoleArn
            ScheduleExpression
            State
            Tags[].Key
            Tags[].Value
            Targets[].Arn
            Targets[].DeadLetterConfig.Arn
            Targets[].Id
            Targets[].Input
            Targets[].InputPath
            Targets[].InputTransformer.InputTemplate
            Targets[].RetryPolicy.MaximumEventAgeInSeconds
            Targets[].RetryPolicy.MaximumRetryAttempts
            Targets[].RoleArn
        """,
        tags="""
            Tags
        """,
    ),
}
