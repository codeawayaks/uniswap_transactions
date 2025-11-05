"""
Uniswap V3 transaction decoder
"""
from typing import Dict, Any, Optional
from web3 import Web3
from eth_utils import to_checksum_address
from decoders.base import BaseDecoder
from utils.abi_loader import V3_ROUTER_ABI
from utils.contract_addresses import UNISWAP_V3_ROUTER
from pool.v3_pool import V3Pool


class V3Decoder(BaseDecoder):
    """Decoder for Uniswap V3 SwapRouter transactions"""
    
    # V3 Router function selectors
    FUNCTION_SELECTORS = {
        "0x414bf389": "exactInputSingle",
        "0xdb3e2198": "exactOutputSingle",
        "0xc04b8d59": "exactInput",
        "0xf28cfc8d": "exactOutput",
        "0x5ae401dc": "multicall",  # V3 Router2 uses multicall
    }
    
    def __init__(self, w3: Web3):
        super().__init__(w3)
        self.pool_querier = V3Pool(w3)
        self.router_address = UNISWAP_V3_ROUTER.lower()
    
    def can_decode(self, tx_input: str, to_address: str) -> bool:
        """Check if this is a V3 router transaction"""
        if not tx_input or len(tx_input) < 10:
            return False
        
        if to_address.lower() != self.router_address:
            return False
        
        selector = self.get_function_selector(tx_input)
        return selector in self.FUNCTION_SELECTORS
    
    def decode(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Decode V3 swap transaction"""
        if not receipt:
            return {
                "version": "v3",
                "success": False,
                "error": "No receipt available",
            }
        
        if receipt.get("status") != 1:
            return {
                "version": "v3",
                "success": False,
                "error": "Transaction failed",
                "transaction_hash": tx.get("hash"),
            }
        
        tx_input = tx.get("input", "")
        selector = self.get_function_selector(tx_input)
        function_name = self.FUNCTION_SELECTORS.get(selector)
        
        if not function_name:
            return {
                "version": "v3",
                "success": False,
                "error": "Unknown function",
            }
        
        # Find the function ABI
        function_abi = None
        for func in V3_ROUTER_ABI:
            if func.get("name") == function_name:
                function_abi = func
                break
        
        if not function_abi:
            return {
                "version": "v3",
                "success": False,
                "error": "Function ABI not found",
            }
        
        # Decode input parameters
        decoded_params = self.decode_input_data(tx_input, function_abi)
        if not decoded_params:
            return {
                "version": "v3",
                "success": False,
                "error": "Failed to decode input",
            }
        
        # Parse transfer events
        transfer_events = self.parse_transfer_events(receipt)
        
        result = {
            "version": "v3",
            "success": True,
            "function": function_name,
            "transaction_hash": tx.get("hash"),
            "block_number": tx.get("blockNumber"),
            "from": to_checksum_address(tx.get("from", "")),
            "to": to_checksum_address(tx.get("to", "")),
        }
        
        # Handle different function types
        if function_name == "exactInputSingle":
            params = decoded_params[0] if decoded_params else None
            if params:
                token_in = to_checksum_address(params[0])
                token_out = to_checksum_address(params[1])
                fee = params[2]
                recipient = to_checksum_address(params[3])
                deadline = params[4]
                amount_in = params[5]
                amount_out_minimum = params[6]
                sqrt_price_limit_x96 = params[7]
                
                token_in_info = self.get_token_info(token_in)
                token_out_info = self.get_token_info(token_out)
                
                result.update({
                    "token_in": token_in_info,
                    "token_out": token_out_info,
                    "token_pair": f"{token_in_info['symbol']}/{token_out_info['symbol']}",
                    "fee": fee,
                    "amount_in": amount_in,
                    "amount_out_minimum": amount_out_minimum,
                    "sqrt_price_limit_x96": sqrt_price_limit_x96,
                })
                
                # Extract actual amounts
                actual_amounts = self._extract_actual_amounts(transfer_events, token_in, token_out)
                result.update(actual_amounts)
                
                # Get pool information
                pool_info = self._get_pool_info(token_in, token_out, fee)
                if pool_info:
                    result["pool_info"] = pool_info
        
        elif function_name == "exactOutputSingle":
            params = decoded_params[0] if decoded_params else None
            if params:
                token_in = to_checksum_address(params[0])
                token_out = to_checksum_address(params[1])
                fee = params[2]
                recipient = to_checksum_address(params[3])
                deadline = params[4]
                amount_out = params[5]
                amount_in_maximum = params[6]
                sqrt_price_limit_x96 = params[7]
                
                token_in_info = self.get_token_info(token_in)
                token_out_info = self.get_token_info(token_out)
                
                result.update({
                    "token_in": token_in_info,
                    "token_out": token_out_info,
                    "token_pair": f"{token_in_info['symbol']}/{token_out_info['symbol']}",
                    "fee": fee,
                    "amount_out": amount_out,
                    "amount_in_maximum": amount_in_maximum,
                    "sqrt_price_limit_x96": sqrt_price_limit_x96,
                })
                
                actual_amounts = self._extract_actual_amounts(transfer_events, token_in, token_out)
                result.update(actual_amounts)
                
                pool_info = self._get_pool_info(token_in, token_out, fee)
                if pool_info:
                    result["pool_info"] = pool_info
        
        elif function_name in ["exactInput", "exactOutput"]:
            params = decoded_params[0] if decoded_params else None
            if params:
                # Multi-hop swaps - path encoded as bytes
                if function_name == "exactInput":
                    token_in = to_checksum_address(params[0])
                    amount_in = params[1]
                    amount_out_minimum = params[2]
                    path = params[3]
                    payer = to_checksum_address(params[4])
                else:  # exactOutput
                    token_in = to_checksum_address(params[0])
                    amount_out = params[1]
                    amount_in_maximum = params[2]
                    path = params[3]
                    payer = to_checksum_address(params[4])
                
                # Decode path (V3 uses packed path encoding)
                path_info = self._decode_v3_path(path)
                
                result.update({
                    "path": path_info,
                    "multi_hop": True,
                })
                
                if path_info:
                    first_pool = path_info[0]
                    last_pool = path_info[-1]
                    
                    token_in_info = self.get_token_info(first_pool["token_in"])
                    token_out_info = self.get_token_info(last_pool["token_out"])
                    
                    result.update({
                        "token_in": token_in_info,
                        "token_out": token_out_info,
                        "token_pair": f"{token_in_info['symbol']}/{token_out_info['symbol']}",
                    })
                    
                    actual_amounts = self._extract_actual_amounts(
                        transfer_events,
                        first_pool["token_in"],
                        last_pool["token_out"]
                    )
                    result.update(actual_amounts)
        
        result["transfer_events"] = transfer_events
        
        return result
    
    def _decode_v3_path(self, path_bytes: bytes) -> list:
        """Decode V3 packed path encoding"""
        # V3 path encoding: token0 (20 bytes) + fee (3 bytes) + token1 (20 bytes) + fee (3 bytes) + ...
        try:
            path_info = []
            offset = 0
            
            while offset < len(path_bytes) - 20:  # Need at least token address
                # Extract token address (20 bytes)
                token_address = "0x" + path_bytes[offset:offset+20].hex()
                offset += 20
                
                if offset + 3 <= len(path_bytes):
                    # Extract fee (3 bytes = uint24)
                    fee = int.from_bytes(path_bytes[offset:offset+3], byteorder='big')
                    offset += 3
                    
                    if offset + 20 <= len(path_bytes):
                        # Extract next token
                        next_token = "0x" + path_bytes[offset:offset+20].hex()
                        offset += 20
                        
                        path_info.append({
                            "token_in": to_checksum_address(token_address),
                            "token_out": to_checksum_address(next_token),
                            "fee": fee,
                        })
                    else:
                        break
                else:
                    break
            
            return path_info
        except Exception as e:
            print(f"Error decoding V3 path: {e}")
            return []
    
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
    
    def _get_pool_info(self, token0: str, token1: str, fee: int) -> Optional[Dict[str, Any]]:
        """Get pool information for a token pair"""
        from utils.contract_addresses import FACTORY_ADDRESSES
        
        try:
            factory_address = FACTORY_ADDRESSES.get("v3")
            if not factory_address:
                return None
            
            pool_address = self.pool_querier.get_pool_address(token0, token1, fee, factory_address)
            if not pool_address:
                return None
            
            pool_state = self.pool_querier.get_pool_state(pool_address)
            if not pool_state:
                return None
            
            # Get token info
            token0_info = self.get_token_info(pool_state["token0"])
            token1_info = self.get_token_info(pool_state["token1"])
            
            # Calculate price from sqrtPriceX96
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
            
            return {
                "pool_address": pool_address,
                "token0": token0_info,
                "token1": token1_info,
                "fee": fee,
                "tick": pool_state["tick"],
                "sqrt_price_x96": pool_state["sqrtPriceX96"],
                "price": prices,
                "liquidity": liquidity,
            }
        except Exception as e:
            print(f"Error getting V3 pool info: {e}")
            return None

