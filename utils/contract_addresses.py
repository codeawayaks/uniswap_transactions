"""
Uniswap contract addresses and ABIs
"""
from config import (
    UNISWAP_V2_ROUTER,
    UNISWAP_V2_FACTORY,
    UNISWAP_V3_ROUTER,
    UNISWAP_V3_ROUTER2,
    UNISWAP_V3_FACTORY,
    UNISWAP_UNIVERSAL_ROUTER,
    UNISWAP_V4_POOL_MANAGER,
)

# Contract address mappings
UNISWAP_ROUTERS = {
    "v2": UNISWAP_V2_ROUTER.lower(),
    "v3": UNISWAP_V3_ROUTER.lower(),
    "v3_router2": UNISWAP_V3_ROUTER2.lower(),
    "universal": UNISWAP_UNIVERSAL_ROUTER.lower(),  # Universal Router (most common)
    "v4": UNISWAP_V4_POOL_MANAGER.lower(),
}

# Factory addresses for pool discovery
FACTORY_ADDRESSES = {
    "v2": UNISWAP_V2_FACTORY.lower(),
    "v3": UNISWAP_V3_FACTORY.lower(),
}

def is_uniswap_router(address: str) -> bool:
    """Check if an address is a known Uniswap router"""
    return address.lower() in UNISWAP_ROUTERS.values()

def get_uniswap_version(address: str) -> str:
    """Get Uniswap version from router address"""
    address_lower = address.lower()
    for version, router_addr in UNISWAP_ROUTERS.items():
        if router_addr == address_lower:
            return version
    return None

