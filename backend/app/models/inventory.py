"""
Product inventory catalog with internal margin floors.
"""

from typing import Dict, List, Optional
from .schemas import ProductInternal, ProductPublic

DEMO_INVENTORY: Dict[str, ProductInternal] = {
    "AMP-01": ProductInternal(
        sku="AMP-01",
        name="Custom CNC 75% Aluminum Mechanical Keyboard Kit (Gasket Mount, Tactile Switches)",
        description=(
            "Anodized 6063 aluminum chassis, FR4 gasket mount plate, hot-swappable PCB, "
            "factory-lubed tactile switches, screw-in stabilizers, and South-facing RGB. "
            "Includes braided USB-C cable and premium carrying case."
        ),
        retail_price=180.00,
        target_price=162.00,
        floor_price=145.00,
        category="Hardware / Peripherals",
        in_stock=True,
        negotiation_notes=(
            "High demand boutique hardware. Push bundle add-ons (wrist rest or switch puller) "
            "if buyer insists on sub-$160 prices. Never concede past $145.00."
        ),
    ),
    "AMP-02": ProductInternal(
        sku="AMP-02",
        name="Vintage 2008 European Final Football Kit (Long Sleeve Collector Edition)",
        description=(
            "Authentic reproduction of the Moscow 2008 European Final long-sleeve kit. "
            "Embroidered match details, high-density breathable fabric, and commemorative sleeve patches."
        ),
        retail_price=95.00,
        target_price=82.00,
        floor_price=72.00,
        category="Apparel / Collectibles",
        in_stock=True,
        negotiation_notes=(
            "Limited deadstock batch. Accept offers down to $82.00. "
            "Maintain resistance between $82.00 and $72.00. Reject below $72.00."
        ),
    ),
    "AMP-03": ProductInternal(
        sku="AMP-03",
        name="DevSecOps Self-Hosted Lab Automation Bundle (Digital License)",
        description=(
            "Production-grade Terraform, Ansible, and Kubernetes recipes for "
            "self-hosted CI/CD, Vault secret management, Prometheus/Grafana monitoring, "
            "and automated PayPal webhook handlers."
        ),
        retail_price=49.00,
        target_price=35.00,
        floor_price=25.00,
        category="Software / Digital",
        in_stock=True,
        negotiation_notes=(
            "Digital license with zero marginal reproduction cost. "
            "Concession floor is $25.00."
        ),
    ),
}


def get_internal_product(sku: str) -> Optional[ProductInternal]:
    return DEMO_INVENTORY.get(sku.upper().strip())


def get_public_product(sku: str) -> Optional[ProductPublic]:
    item = get_internal_product(sku)
    return item.to_public() if item else None


def get_public_catalog() -> List[ProductPublic]:
    return [product.to_public() for product in DEMO_INVENTORY.values()]
