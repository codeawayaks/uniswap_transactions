"""
Uniswap V4 Pool query utilities
"""
from typing import Dict, Any, Optional, Tuple
from web3 import Web3
from eth_utils import to_checksum_address
from utils.abi_loader import V4_POOL_MANAGER_ABI
from math import sqrt


class V4Pool:
    """Query Uniswap V4 pool state"""
    
    def __init__(self, w3: Web3):
        self.w3 = w3
    
    def get_pool(self, pool_manager_address: str, pool_key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get pool state from V4 PoolManager"""
        try:
            contract = self.w3.eth.contract(
                address=to_checksum_address(pool_manager_address),
                abi=V4_POOL_MANAGER_ABI
            )
            
            # Build pool key tuple
            key_tuple = (
                to_checksum_address(pool_key["currency0"]),
                to_checksum_address(pool_key["currency1"]),
                pool_key["fee"],
                pool_key["tickSpacing"],
                to_checksum_address(pool_key.get("hooks", "0x0000000000000000000000000000000000000000")),
            )
            
            result = contract.functions.getPool(key_tuple).call()
            
            return {
                "sqrtPriceX96": result[0],
                "liquidity": result[1],
                "tick": result[2],
            }
        except Exception as e:
            print(f"Error getting V4 pool: {e}")
            return None
    
    def get_pool_id(self, pool_key: Dict[str, Any]) -> str:
        """Calculate pool ID from pool key (for reference)"""
        # V4 uses keccak256(abi.encode(poolKey)) as pool ID
        from eth_utils import keccak, encode_hex
        from eth_abi import encode
        
        try:
            key_tuple = (
                to_checksum_address(pool_key["currency0"]),
                to_checksum_address(pool_key["currency1"]),
                pool_key["fee"],
                pool_key["tickSpacing"],
                to_checksum_address(pool_key.get("hooks", "0x0000000000000000000000000000000000000000")),
            )
            
            encoded = encode(
                ['address', 'address', 'uint24', 'int24', 'address'],
                key_tuple
            )
            
            pool_id = keccak(encoded)
            return encode_hex(pool_id)
        except Exception as e:
            print(f"Error calculating pool ID: {e}")
            return None
    
    def sqrt_price_x96_to_price(self, sqrt_price_x96: int, decimals0: int = 18, decimals1: int = 18) -> Dict[str, float]:
        """Convert sqrtPriceX96 to actual token price (same as V3)"""
        Q96 = 2 ** 96
        sqrt_price = sqrt_price_x96 / Q96
        price = sqrt_price ** 2
        
        # Adjust for decimals
        decimal_adjustment = 10 ** (decimals0 - decimals1)
        adjusted_price = price * decimal_adjustment
        
        price_token1_in_token0 = adjusted_price
        price_token0_in_token1 = 1 / adjusted_price if adjusted_price > 0 else 0
        
        return {
            "token1_price_in_token0": price_token1_in_token0,
            "token0_price_in_token1": price_token0_in_token1,
            "sqrt_price_x96": sqrt_price_x96,
        }
    
    def tick_to_price(self, tick: int, decimals0: int = 18, decimals1: int = 18) -> Dict[str, float]:
        """Convert tick to price"""
        price = 1.0001 ** tick
        
        decimal_adjustment = 10 ** (decimals0 - decimals1)
        adjusted_price = price * decimal_adjustment
        
        price_token1_in_token0 = adjusted_price
        price_token0_in_token1 = 1 / adjusted_price if adjusted_price > 0 else 0
        
        return {
            "token1_price_in_token0": price_token1_in_token0,
            "token0_price_in_token1": price_token0_in_token1,
            "tick": tick,
        }
    
    def calculate_liquidity_value(self, liquidity: int, sqrt_price_x96: int, decimals0: int = 18, decimals1: int = 18) -> Dict[str, Any]:
        """Calculate liquidity value from V4 pool"""
        Q96 = 2 ** 96
        sqrt_price = sqrt_price_x96 / Q96
        
        liquidity_formatted = liquidity / (10 ** 18)  # Approximation
        
        return {
            "liquidity": liquidity,
            "liquidity_formatted": liquidity_formatted,
            "sqrt_price_x96": sqrt_price_x96,
        }

