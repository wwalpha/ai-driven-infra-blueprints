"""Static SSO comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "SSO.Assignment": properties(
        scalars="""
            InstanceArn
            PermissionSetArn
            PrincipalId
            PrincipalType
            TargetId
            TargetType
        """,
    ),
    "SSO.PermissionSet": properties(
        objects="""
            CustomerManagedPolicyReferences[]
            InlinePolicy
            PermissionsBoundary
            PermissionsBoundary.CustomerManagedPolicyReference
            Tags[]
        """,
        ordered="""
            CustomerManagedPolicyReferences
            ManagedPolicies
        """,
        scalars="""
            CustomerManagedPolicyReferences[].Name
            CustomerManagedPolicyReferences[].Path
            Description
            InstanceArn
            Name
            PermissionsBoundary.CustomerManagedPolicyReference.Name
            PermissionsBoundary.CustomerManagedPolicyReference.Path
            PermissionsBoundary.ManagedPolicyArn
            RelayStateType
            SessionDuration
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
}
