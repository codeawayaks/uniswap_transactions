"""
Configuration settings for Uniswap transaction decoder
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Ethereum RPC Configuration
ETHEREUM_RPC_URL = os.getenv("ETHEREUM_RPC_URL", "https://eth.llamarpc.com")
ETHEREUM_WSS_URL = os.getenv("ETHEREUM_WSS_URL", "wss://eth.llamarpc.com")

# Alternative RPC providers (fallback)
BACKUP_RPC_URLS = [
    "https://rpc.ankr.com/eth",
    "https://eth-mainnet.public.blastapi.io",
]

# Monitoring Configuration
BLOCK_CONFIRMATIONS = int(os.getenv("BLOCK_CONFIRMATIONS", "12"))
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL", "12"))  # seconds
WEBSOCKET_TIMEOUT = int(os.getenv("WEBSOCKET_TIMEOUT", "30"))  # seconds
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "5"))  # seconds

# Output Configuration
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Uniswap Contract Addresses
UNISWAP_V2_ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
UNISWAP_V2_FACTORY = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
UNISWAP_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
UNISWAP_V3_ROUTER2 = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"
UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
UNISWAP_UNIVERSAL_ROUTER = "0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD"  # Universal Router (most common now)
UNISWAP_V4_POOL_MANAGER = "0x0000000000000000000000000000000000000000"  # Update with actual V4 address

