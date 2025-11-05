"""
Uniswap V4 transaction decoder
"""
from typing import Dict, Any, Optional
from web3 import Web3
from eth_utils import to_checksum_address, decode_hex
from eth_abi import decode
from decoders.base import BaseDecoder
from utils.contract_addresses import UNISWAP_V4_POOL_MANAGER
from pool.v4_pool import V4Pool


class V4Decoder(BaseDecoder):
    """Decoder for Uniswap V4 PoolManager transactions"""
    
    # V4 PoolManager function selectors
    # Note: V4 uses hooks and different architecture
    FUNCTION_SELECTORS = {
        "0x128acb08": "swap",  # Main swap function with hooks
        "0x9c395bc2": "lock",  # Flash accounting lock
        "0x3d582197": "settle",  # Flash accounting settle
        "0x6a627842": "mint",  # Mint liquidity
        "0x0c49ccbe": "burn",  # Burn liquidity
    }
    
    def __init__(self, w3: Web3):
        super().__init__(w3)
        self.pool_querier = V4Pool(w3)
        self.pool_manager_address = UNISWAP_V4_POOL_MANAGER.lower()
    
    def can_decode(self, tx_input: str, to_address: str) -> bool:
        """Check if this is a V4 PoolManager transaction"""
        if not tx_input or len(tx_input) < 10:
            return False
        
        # V4 can be called through various interfaces
        # Check if it's a direct PoolManager call or through a hook/router
        if to_address.lower() == self.pool_manager_address:
            selector = self.get_function_selector(tx_input)
            return selector in self.FUNCTION_SELECTORS
        
        # Also check if transaction involves V4 pool (check events/logs)
        # For now, we'll check if it's a known V4 router/hook
        return False
    
    def decode(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Decode V4 swap transaction"""
        if not receipt:
            return {
                "version": "v4",
                "success": False,
                "error": "No receipt available",
            }
        
        if receipt.get("status") != 1:
            return {
                "version": "v4",
                "success": False,
                "error": "Transaction failed",
                "transaction_hash": tx.get("hash"),
            }
        
        tx_input = tx.get("input", "")
        selector = self.get_function_selector(tx_input)
        function_name = self.FUNCTION_SELECTORS.get(selector)
        
        if not function_name:
            # Try to decode from events/logs
            return self._decode_from_events(tx, receipt)
        
        result = {
            "version": "v4",
            "success": True,
            "function": function_name,
            "transaction_hash": tx.get("hash"),
            "block_number": tx.get("blockNumber"),
            "from": to_checksum_address(tx.get("from", "")),
            "to": to_checksum_address(tx.get("to", "")),
        }
        
        # Handle swap function
        if function_name == "swap":
            swap_data = self._decode_swap(tx_input)
            if swap_data:
                result.update(swap_data)
                
                # Get pool information
                if "pool_key" in swap_data:
                    pool_info = self._get_pool_info(swap_data["pool_key"])
                    if pool_info:
                        result["pool_info"] = pool_info
        
        # Parse transfer events
        transfer_events = self.parse_transfer_events(receipt)
        result["transfer_events"] = transfer_events
        
        # Extract token amounts from events if not already decoded
        if "token_in" in result and "token_out" in result:
            actual_amounts = self._extract_actual_amounts(
                transfer_events,
                result["token_in"]["address"],
                result["token_out"]["address"]
            )
            result.update(actual_amounts)
        
        return result
    
    def _decode_swap(self, tx_input: str) -> Optional[Dict[str, Any]]:
        """Decode V4 swap function"""
        try:
            # V4 swap function signature varies, but typically:
            # swap(PoolKey memory poolKey, IPoolManager.SwapParams memory params, bytes calldata hookData)
            
            # Remove selector
            if len(tx_input) < 10:
                return None
            
            encoded_params = tx_input[10:]
            
            # Try to decode - structure may vary
            # This is a simplified decoder - actual implementation depends on V4 final ABI
            try:
                # PoolKey structure
                # (address currency0, address currency1, uint24 fee, int24 tickSpacing, address hooks)
                pool_key_types = ['address', 'address', 'uint24', 'int24', 'address']
                # SwapParams structure (simplified - actual may differ)
                # (bool zeroForOne, int256 amountSpecified, uint160 sqrtPriceLimitX96)
                swap_params_types = ['bool', 'int256', 'uint160']
                
                # Decode pool key
                pool_key_decoded = decode(pool_key_types, decode_hex(encoded_params[:520]))  # Approximate size
                
                pool_key = {
                    "currency0": to_checksum_address(pool_key_decoded[0]),
                    "currency1": to_checksum_address(pool_key_decoded[1]),
                    "fee": pool_key_decoded[2],
                    "tickSpacing": pool_key_decoded[3],
                    "hooks": to_checksum_address(pool_key_decoded[4]),
                }
                
                # Get token info
                token0_info = self.get_token_info(pool_key["currency0"])
                token1_info = self.get_token_info(pool_key["currency1"])
                
                return {
                    "pool_key": pool_key,
                    "token_in": token0_info if pool_key_decoded[0] else token1_info,
                    "token_out": token1_info if pool_key_decoded[0] else token0_info,
                    "token_pair": f"{token0_info['symbol']}/{token1_info['symbol']}",
                    "fee": pool_key["fee"],
                    "tick_spacing": pool_key["tickSpacing"],
                    "hooks": pool_key["hooks"],
                }
            except Exception as e:
                print(f"Error decoding V4 swap parameters: {e}")
                return None
        except Exception as e:
            print(f"Error in _decode_swap: {e}")
            return None
    
    def _decode_from_events(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Try to decode V4 transaction from events"""
        # V4 emits specific events that can help identify swaps
        # This is a fallback method
        
        transfer_events = self.parse_transfer_events(receipt)
        
        if len(transfer_events) < 2:
            return {
                "version": "v4",
                "success": False,
                "error": "Insufficient transfer events",
            }
        
        # Try to identify token pair from transfers
        tokens = set(event["token"].lower() for event in transfer_events)
        
        if len(tokens) >= 2:
            token_list = list(tokens)
            token_in_addr = token_list[0]
            token_out_addr = token_list[1]
            
            token_in_info = self.get_token_info(token_in_addr)
            token_out_info = self.get_token_info(token_out_addr)
            
            actual_amounts = self._extract_actual_amounts(
                transfer_events,
                token_in_addr,
                token_out_addr
            )
            
            return {
                "version": "v4",
                "success": True,
                "function": "swap (inferred)",
                "transaction_hash": tx.get("hash"),
                "block_number": tx.get("blockNumber"),
                "from": to_checksum_address(tx.get("from", "")),
                "to": to_checksum_address(tx.get("to", "")),
                "token_in": token_in_info,
                "token_out": token_out_info,
                "token_pair": f"{token_in_info['symbol']}/{token_out_info['symbol']}",
                "transfer_events": transfer_events,
                **actual_amounts,
            }
        
        return {
            "version": "v4",
            "success": False,
            "error": "Could not decode from events",
        }
    
    def _extract_actual_amounts(self, transfer_events: list, token_in: str, token_out: str) -> Dict[str, Any]:
        """Extract actual swap amounts from transfer events"""
        token_in = token_in.lower()
        token_out = token_out.lower()
        
        amount_in = 0
        amount_out = 0
        token_in_decimals = 18
        token_out_decimals = 18
        
        for event in transfer_events:
            event_token = event["token"].lower()
            if event_token == token_in:
                amount_in += event["amount"]
                token_info = self.get_token_info(event["token"])
                token_in_decimals = token_info.get("decimals", 18)
            elif event_token == token_out:
                amount_out += event["amount"]
                token_info = self.get_token_info(event["token"])
                token_out_decimals = token_info.get("decimals", 18)
        
        return {
            "amount_in_actual": amount_in,
            "amount_out_actual": amount_out,
            "amount_in_formatted": self.format_amount(amount_in, token_in_decimals),
            "amount_out_formatted": self.format_amount(amount_out, token_out_decimals),
        }
    
    def _get_pool_info(self, pool_key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get pool information for a pool key"""
        try:
            pool_state = self.pool_querier.get_pool(UNISWAP_V4_POOL_MANAGER, pool_key)
            if not pool_state:
                return None
            
            # Get token info
            token0_info = self.get_token_info(pool_key["currency0"])
            token1_info = self.get_token_info(pool_key["currency1"])
            
            # Calculate price
            prices = self.pool_querier.sqrt_price_x96_to_price(
                pool_state["sqrtPriceX96"],
                token0_info["decimals"],
                token1_info["decimals"]
            )
            
            # Calculate liquidity
            liquidity = self.pool_querier.calculate_liquidity_value(
                pool_state["liquidity"],
                pool_state["sqrtPriceX96"],
                token0_info["decimals"],
                token1_info["decimals"]
            )
            
            # Get pool ID
            pool_id = self.pool_querier.get_pool_id(pool_key)
            
            return {
                "pool_id": pool_id,
                "pool_key": pool_key,
                "token0": token0_info,
                "token1": token1_info,
                "fee": pool_key["fee"],
                "tick_spacing": pool_key["tickSpacing"],
                "hooks": pool_key.get("hooks"),
                "tick": pool_state["tick"],
                "sqrt_price_x96": pool_state["sqrtPriceX96"],
                "price": prices,
                "liquidity": liquidity,
            }
        except Exception as e:
            print(f"Error getting V4 pool info: {e}")
            return None

