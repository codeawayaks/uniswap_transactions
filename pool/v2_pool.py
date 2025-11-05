"""
Uniswap V2 Pool query utilities
"""
from typing import Dict, Any, Optional
from web3 import Web3
from eth_utils import to_checksum_address
from utils.abi_loader import V2_POOL_ABI


class V2Pool:
    """Query Uniswap V2 pool state"""
    
    def __init__(self, w3: Web3):
        self.w3 = w3
    
    def get_pool_address(self, token0: str, token1: str, factory_address: str) -> Optional[str]:
        """Get pool address from factory using CREATE2"""
        # V2 uses CREATE2 for deterministic pool addresses
        # Pool address = keccak256(abi.encodePacked(
        #     hex'ff',
        #     factory,
        #     keccak256(abi.encodePacked(token0, token1)),
        #     hex'96e8ac4277198ff8b6f785478aa9a39f403cb768dd02cbee326c3e7da348845f'
        # ))
        from eth_utils import keccak, encode_hex
        from eth_abi import encode
        
        # Sort tokens to ensure consistent address
        token0 = to_checksum_address(token0)
        token1 = to_checksum_address(token1)
        if token0.lower() > token1.lower():
            token0, token1 = token1, token0
        
        # Encode tokens
        packed = encode(['address', 'address'], [token0, token1])
        salt = keccak(packed)
        
        # CREATE2 init code hash for V2
        init_code_hash = "0x96e8ac4277198ff8b6f785478aa9a39f403cb768dd02cbee326c3e7da348845f"
        
        # Create2 calculation
        factory_bytes = bytes.fromhex(to_checksum_address(factory_address)[2:])
        salt_bytes = salt
        init_code_bytes = bytes.fromhex(init_code_hash[2:])
        
        data = b'\xff' + factory_bytes + salt_bytes + init_code_bytes
        pool_address = keccak(data)
        
        return to_checksum_address(encode_hex(pool_address)[2:])
    
    def get_reserves(self, pool_address: str) -> Optional[Dict[str, Any]]:
        """Get reserves from V2 pool"""
        try:
            contract = self.w3.eth.contract(
                address=to_checksum_address(pool_address),
                abi=V2_POOL_ABI
            )
            
            reserves = contract.functions.getReserves().call()
            token0 = contract.functions.token0().call()
            token1 = contract.functions.token1().call()
            
            return {
                "reserve0": reserves[0],
                "reserve1": reserves[1],
                "token0": to_checksum_address(token0),
                "token1": to_checksum_address(token1),
                "blockTimestampLast": reserves[2],
            }
        except Exception as e:
            print(f"Error getting V2 pool reserves: {e}")
            return None
    
    def calculate_price(self, reserve0: int, reserve1: int, decimals0: int = 18, decimals1: int = 18) -> Dict[str, float]:
        """Calculate token prices from reserves"""
        # Adjust for decimals
        adjusted_reserve0 = reserve0 / (10 ** decimals0)
        adjusted_reserve1 = reserve1 / (10 ** decimals1)
        
        # Price of token1 in terms of token0
        price_token1_in_token0 = adjusted_reserve0 / adjusted_reserve1 if adjusted_reserve1 > 0 else 0
        
        # Price of token0 in terms of token1
        price_token0_in_token1 = adjusted_reserve1 / adjusted_reserve0 if adjusted_reserve0 > 0 else 0
        
        return {
            "token1_price_in_token0": price_token1_in_token0,
            "token0_price_in_token1": price_token0_in_token1,
        }
    
    def calculate_liquidity(self, reserve0: int, reserve1: int, decimals0: int = 18, decimals1: int = 18) -> Dict[str, Any]:
        """Calculate liquidity metrics"""
        adjusted_reserve0 = reserve0 / (10 ** decimals0)
        adjusted_reserve1 = reserve1 / (10 ** decimals1)
        
        # Total liquidity (geometric mean)
        total_liquidity = (adjusted_reserve0 * adjusted_reserve1) ** 0.5
        
        return {
            "reserve0": adjusted_reserve0,
            "reserve1": adjusted_reserve1,
            "total_liquidity": total_liquidity,
            "total_value_usd": None,  # Would need price oracle
        }

