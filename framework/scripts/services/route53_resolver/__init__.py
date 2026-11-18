"""route53-resolver service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "route53-resolver",
    (
        "Route53Resolver.ResolverEndpoint",
        "Route53Resolver.ResolverRule",
        "Route53Resolver.ResolverRuleAssociation",
    ),
    REFERENCES,
    package="route53_resolver",
)
