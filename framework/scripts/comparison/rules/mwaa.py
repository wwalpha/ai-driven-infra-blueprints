"""Static MWAA comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "MWAA.Environment": properties(
        objects="""
            AirflowConfigurationOptions
            LoggingConfiguration
            LoggingConfiguration.DagProcessingLogs
            LoggingConfiguration.SchedulerLogs
            LoggingConfiguration.TaskLogs
            LoggingConfiguration.WebserverLogs
            LoggingConfiguration.WorkerLogs
            NetworkConfiguration
            Tags
        """,
        ordered="""
            NetworkConfiguration.SecurityGroupIds
            NetworkConfiguration.SubnetIds
        """,
        references="""
            KmsKey
        """,
        scalars="""
            AirflowVersion
            DagS3Path
            EndpointManagement
            EnvironmentClass
            ExecutionRoleArn
            LoggingConfiguration.DagProcessingLogs.Enabled
            LoggingConfiguration.DagProcessingLogs.LogLevel
            LoggingConfiguration.SchedulerLogs.Enabled
            LoggingConfiguration.SchedulerLogs.LogLevel
            LoggingConfiguration.TaskLogs.Enabled
            LoggingConfiguration.TaskLogs.LogLevel
            LoggingConfiguration.WebserverLogs.Enabled
            LoggingConfiguration.WebserverLogs.LogLevel
            LoggingConfiguration.WorkerLogs.Enabled
            LoggingConfiguration.WorkerLogs.LogLevel
            MaxWebservers
            MaxWorkers
            MinWebservers
            MinWorkers
            Name
            PluginsS3ObjectVersion
            PluginsS3Path
            RequirementsS3ObjectVersion
            RequirementsS3Path
            Schedulers
            SourceBucketArn
            StartupScriptS3ObjectVersion
            StartupScriptS3Path
            WebserverAccessMode
            WeeklyMaintenanceWindowStart
            WorkerReplacementStrategy
        """,
    ),
}
