"""Fixed quicksight design definitions; no display-engine dependencies."""


RESOURCE_REFERENCE_PROPERTIES = {
    'QuickSight.DataSource.Permissions[].Principal': ('QuickSight.Group', 'GroupName'),
}

HIDDEN_PROPERTIES = {'QuickSight.Group.Arn'}

QUICKSIGHT_GROUP = "QuickSight.Group"
