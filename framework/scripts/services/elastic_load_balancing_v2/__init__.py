"""ElasticLoadBalancingV2 service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "elastic-load-balancing-v2",
    (
        "ElasticLoadBalancingV2.Listener",
        "ElasticLoadBalancingV2.ListenerCertificate",
        "ElasticLoadBalancingV2.ListenerRule",
        "ElasticLoadBalancingV2.LoadBalancer",
        "ElasticLoadBalancingV2.TargetGroup",
    ),
    REFERENCES,
    package="elastic_load_balancing_v2",
)
