"""network-firewall service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "network-firewall",
    (
        "NetworkFirewall.Firewall",
        "NetworkFirewall.FirewallPolicy",
        "NetworkFirewall.LoggingConfiguration",
        "NetworkFirewall.RuleGroup",
    ),
    REFERENCES,
    package="network_firewall",
)
