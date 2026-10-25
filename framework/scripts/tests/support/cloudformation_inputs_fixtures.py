"""Condition inputs shared by pure evaluation and Comparison evidence checks."""

conditions = {
    "IsEnabled": {"Fn::Equals": [{"Ref": "Enable"}, "true"]},
    "OtherEnabled": {"Fn::Equals": [{"Ref": "Other"}, "yes"]},
    "Combined": {
        "Fn::And": [
            {"Condition": "IsEnabled"},
            {
                "Fn::Or": [
                    {"Condition": "OtherEnabled"},
                    {"Fn::Not": [{"Condition": "IsEnabled"}]},
                ]
            },
        ]
    },
    "Branch": {"Fn::If": ["IsEnabled", {"Condition": "Missing"}, False]},
    "SubOff": {"Fn::Equals": [{"Fn::Sub": "${Enable}"}, "true"]},
}
condition_document = {
    "Parameters": {
        "Enable": {"Type": "String", "Default": "false"},
        "Other": {"Type": "String", "Default": "yes"},
    },
    "Conditions": conditions,
}
