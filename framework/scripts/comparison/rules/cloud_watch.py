"""Static CloudWatch comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "CloudWatch.Alarm": properties(
        objects="""
            Dimensions[]
            Metrics[]
            Metrics[].MetricStat
            Metrics[].MetricStat.Metric
            Metrics[].MetricStat.Metric.Dimensions[]
            Tags[]
        """,
        ordered="""
            AlarmActions
            Dimensions
            InsufficientDataActions
            Metrics
            Metrics[].MetricStat.Metric.Dimensions
            OKActions
        """,
        scalars="""
            ActionsEnabled
            AlarmDescription
            AlarmName
            ComparisonOperator
            DatapointsToAlarm
            Dimensions[].Name
            Dimensions[].Value
            EvaluateLowSampleCountPercentile
            EvaluationPeriods
            ExtendedStatistic
            MetricName
            Metrics[].AccountId
            Metrics[].Expression
            Metrics[].Id
            Metrics[].Label
            Metrics[].MetricStat.Metric.Dimensions[].Name
            Metrics[].MetricStat.Metric.Dimensions[].Value
            Metrics[].MetricStat.Metric.MetricName
            Metrics[].MetricStat.Metric.Namespace
            Metrics[].MetricStat.Period
            Metrics[].MetricStat.Stat
            Metrics[].MetricStat.Unit
            Metrics[].Period
            Metrics[].ReturnData
            Namespace
            Period
            Statistic
            Tags[].Key
            Tags[].Value
            Threshold
            ThresholdMetricId
            TreatMissingData
            Unit
        """,
        tags="""
            Tags
        """,
    ),
    "CloudWatch.Dashboard": properties(
        objects="""
            Tags[]
        """,
        scalars="""
            DashboardBody
            DashboardName
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
}
