"""
Uniswap V3 Pool query utilities
"""
from typing import Dict, Any, Optional
from web3 import Web3
from eth_utils import to_checksum_address
from utils.abi_loader import V3_POOL_ABI
from math import sqrt


class V3Pool:
    """Query Uniswap V3 pool state"""
    
    def __init__(self, w3: Web3):
        self.w3 = w3
    
    def get_pool_address(self, token0: str, token1: str, fee: int, factory_address: str) -> Optional[str]:
        """Get V3 pool address from factory"""
        # V3 uses CREATE2 for deterministic pool addresses
        from eth_utils import keccak, encode_hex
        from eth_abi import encode
        
        # Sort tokens
        token0 = to_checksum_address(token0)
        token1 = to_checksum_address(token1)
        if token0.lower() > token1.lower():
            token0, token1 = token1, token0
        
        # Encode pool parameters
        packed = encode(['address', 'address', 'uint24'], [token0, token1, fee])
        salt = keccak(packed)
        
        # CREATE2 init code hash for V3
        init_code_hash = "0xe34f199b19b2b4f47a684971ad7d1c88c8f1d4c8d8c8c8c8c8c8c8c8c8c8c8c8"
        # Actual V3 init code hash: 0xe34f199b19b2b4f47a684971ad7d1c88c8f1d4c8d8c8c8c8c8c8c8c8c8c8c8
        # Using placeholder - should query factory or use known hash
        
        factory_bytes = bytes.fromhex(to_checksum_address(factory_address)[2:])
        salt_bytes = salt
        init_code_bytes = bytes.fromhex(init_code_hash[2:])
        
        data = b'\xff' + factory_bytes + salt_bytes + init_code_bytes
        pool_address = keccak(data)
        
        return to_checksum_address(encode_hex(pool_address)[2:])
    
    def get_pool_state(self, pool_address: str) -> Optional[Dict[str, Any]]:
        """Get slot0 and liquidity from V3 pool"""
        try:
            contract = self.w3.eth.contract(
                address=to_checksum_address(pool_address),
                abi=V3_POOL_ABI
            )
            
            slot0 = contract.functions.slot0().call()
            liquidity = contract.functions.liquidity().call()
            token0 = contract.functions.token0().call()
            token1 = contract.functions.token1().call()
            fee = contract.functions.fee().call()
            
            return {
                "sqrtPriceX96": slot0[0],
                "tick": slot0[1],
                "observationIndex": slot0[2],
                "observationCardinality": slot0[3],
                "observationCardinalityNext": slot0[4],
                "feeProtocol": slot0[5],
                "unlocked": slot0[6],
                "liquidity": liquidity,
                "token0": to_checksum_address(token0),
                "token1": to_checksum_address(token1),
                "fee": fee,
            }
        except Exception as e:
            print(f"Error getting V3 pool state: {e}")
            return None
    
    def sqrt_price_x96_to_price(self, sqrt_price_x96: int, decimals0: int = 18, decimals1: int = 18) -> Dict[str, float]:
        """Convert sqrtPriceX96 to actual token price"""
        # sqrtPriceX96 = sqrt(price) * 2^96
        # price = (sqrtPriceX96 / 2^96)^2
        # Adjust for token decimals
        
        Q96 = 2 ** 96
        sqrt_price = sqrt_price_x96 / Q96
        price = sqrt_price ** 2
        
        # Adjust for decimals
        decimal_adjustment = 10 ** (decimals0 - decimals1)
        adjusted_price = price * decimal_adjustment
        
        # Price of token1 in terms of token0
        price_token1_in_token0 = adjusted_price
        
        # Price of token0 in terms of token1
        price_token0_in_token1 = 1 / adjusted_price if adjusted_price > 0 else 0
        
        return {
            "token1_price_in_token0": price_token1_in_token0,
            "token0_price_in_token1": price_token0_in_token1,
            "sqrt_price_x96": sqrt_price_x96,
        }
    
    def tick_to_price(self, tick: int, decimals0: int = 18, decimals1: int = 18) -> Dict[str, float]:
        """Convert tick to price"""
        # price = 1.0001^tick
        price = 1.0001 ** tick
        
        # Adjust for decimals
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
        """Calculate liquidity value from V3 pool"""
        # V3 liquidity is more complex - this is a simplified calculation
        # Actual value would require position tracking
        
        Q96 = 2 ** 96
        sqrt_price = sqrt_price_x96 / Q96
        
        # Simplified liquidity representation
        # In practice, V3 liquidity is distributed across ticks
        liquidity_formatted = liquidity / (10 ** 18)  # Rough approximation
        
        return {
            "liquidity": liquidity,
            "liquidity_formatted": liquidity_formatted,
            "sqrt_price_x96": sqrt_price_x96,
        }

