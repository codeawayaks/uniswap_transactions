"""
Uniswap V2 transaction decoder
"""
from typing import Dict, Any, Optional
from web3 import Web3
from eth_utils import to_checksum_address
from decoders.base import BaseDecoder
from utils.abi_loader import V2_ROUTER_ABI, get_function_selector
from utils.contract_addresses import UNISWAP_V2_ROUTER
from pool.v2_pool import V2Pool


class V2Decoder(BaseDecoder):
    """Decoder for Uniswap V2 Router02 transactions"""
    
    # V2 Router function selectors
    FUNCTION_SELECTORS = {
        "0x38ed1739": "swapExactTokensForTokens",
        "0x8803dbee": "swapTokensForExactTokens",
        "0x7ff36ab5": "swapExactETHForTokens",
        "0x4a25d94a": "swapETHForExactTokens",
        "0x5c11d795": "swapExactTokensForTokensSupportingFeeOnTransferTokens",
        "0x791ac947": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "0x02751cec": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "0xb6f9de95": "swapExactETHForTokensSupportingFeeOnTransferTokens",
    }
    
    def __init__(self, w3: Web3):
        super().__init__(w3)
        self.pool_querier = V2Pool(w3)
        self.router_address = UNISWAP_V2_ROUTER.lower()
    
    def can_decode(self, tx_input: str, to_address: str) -> bool:
        """Check if this is a V2 router transaction"""
        if not tx_input or len(tx_input) < 10:
            return False
        
        if to_address.lower() != self.router_address:
            return False
        
        selector = self.get_function_selector(tx_input)
        return selector in self.FUNCTION_SELECTORS
    
    def decode(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Decode V2 swap transaction"""
        if not receipt:
            return {
                "version": "v2",
                "success": False,
                "error": "No receipt available",
            }
        
        if receipt.get("status") != 1:
            return {
                "version": "v2",
                "success": False,
                "error": "Transaction failed",
                "transaction_hash": tx.get("hash"),
            }
        
        tx_input = tx.get("input", "")
        selector = self.get_function_selector(tx_input)
        function_name = self.FUNCTION_SELECTORS.get(selector)
        
        if not function_name:
            return {
                "version": "v2",
                "success": False,
                "error": "Unknown function",
            }
        
        # Find the function ABI
        function_abi = None
        for func in V2_ROUTER_ABI:
            if func.get("name") == function_name:
                function_abi = func
                break
        
        if not function_abi:
            return {
                "version": "v2",
                "success": False,
                "error": "Function ABI not found",
            }
        
        # Decode input parameters
        decoded_params = self.decode_input_data(tx_input, function_abi)
        if not decoded_params:
            return {
                "version": "v2",
                "success": False,
                "error": "Failed to decode input",
            }
        
        # Parse transfer events to get actual amounts
        transfer_events = self.parse_transfer_events(receipt)
        
        # Extract path and amounts based on function
        result = {
            "version": "v2",
            "success": True,
            "function": function_name,
            "transaction_hash": tx.get("hash"),
            "block_number": tx.get("blockNumber"),
            "from": to_checksum_address(tx.get("from", "")),
            "to": to_checksum_address(tx.get("to", "")),
        }
        
        # Handle different function types
        if "ExactTokensForTokens" in function_name or "TokensForExactTokens" in function_name:
            # Standard token swaps
            if len(decoded_params) >= 5:
                amount_in = decoded_params[0] if "Exact" in function_name else decoded_params[1]
                amount_out_min = decoded_params[1] if "Exact" in function_name else decoded_params[0]
                path = decoded_params[2]
                to_address = decoded_params[3]
                deadline = decoded_params[4]
                
                result.update({
                    "amount_in": amount_in,
                    "amount_out_min": amount_out_min,
                    "path": [to_checksum_address(addr) for addr in path],
                    "deadline": deadline,
                })
                
                # Extract token pair
                if len(path) >= 2:
                    token_in = to_checksum_address(path[0])
                    token_out = to_checksum_address(path[-1])
                    
                    token_in_info = self.get_token_info(token_in)
                    token_out_info = self.get_token_info(token_out)
                    
                    result.update({
                        "token_in": token_in_info,
                        "token_out": token_out_info,
                        "token_pair": f"{token_in_info['symbol']}/{token_out_info['symbol']}",
                    })
                    
                    # Get actual amounts from transfer events
                    actual_amounts = self._extract_actual_amounts(transfer_events, token_in, token_out)
                    result.update(actual_amounts)
                    
                    # Query pool information for first pool in path
                    if len(path) >= 2:
                        pool_info = self._get_pool_info(path[0], path[1])
                        if pool_info:
                            result["pool_info"] = pool_info
        
        elif "ETH" in function_name:
            # ETH swaps
            weth_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"  # WETH
            
            if "ExactETHForTokens" in function_name:
                amount_in = tx.get("value", 0)
                amount_out_min = decoded_params[0] if len(decoded_params) > 0 else 0
                path = decoded_params[1] if len(decoded_params) > 1 else []
            else:  # ETHForExactTokens
                amount_out = decoded_params[0] if len(decoded_params) > 0 else 0
                amount_in_max = decoded_params[1] if len(decoded_params) > 1 else 0
                path = decoded_params[2] if len(decoded_params) > 2 else []
            
            if path:
                token_out = to_checksum_address(path[-1])
                token_out_info = self.get_token_info(token_out)
                
                result.update({
                    "token_in": {"address": weth_address, "symbol": "ETH", "decimals": 18, "name": "Ether"},
                    "token_out": token_out_info,
                    "token_pair": f"ETH/{token_out_info['symbol']}",
                })
                
                # Get actual amounts from transfer events
                actual_amounts = self._extract_actual_amounts(transfer_events, weth_address, token_out)
                result.update(actual_amounts)
        
        result["transfer_events"] = transfer_events
        
        return result
    
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
                # Get decimals from token info if available
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
    
    def _get_pool_info(self, token0: str, token1: str) -> Optional[Dict[str, Any]]:
        """Get pool information for a token pair"""
        from utils.contract_addresses import FACTORY_ADDRESSES
        
        try:
            factory_address = FACTORY_ADDRESSES.get("v2")
            if not factory_address:
                return None
            
            pool_address = self.pool_querier.get_pool_address(token0, token1, factory_address)
            if not pool_address:
                return None
            
            reserves = self.pool_querier.get_reserves(pool_address)
            if not reserves:
                return None
            
            # Get token info for decimals
            token0_info = self.get_token_info(reserves["token0"])
            token1_info = self.get_token_info(reserves["token1"])
            
            # Calculate price and liquidity
            prices = self.pool_querier.calculate_price(
                reserves["reserve0"],
                reserves["reserve1"],
                token0_info["decimals"],
                token1_info["decimals"]
            )
            
            liquidity = self.pool_querier.calculate_liquidity(
                reserves["reserve0"],
                reserves["reserve1"],
                token0_info["decimals"],
                token1_info["decimals"]
            )
            
            return {
                "pool_address": pool_address,
                "token0": token0_info,
                "token1": token1_info,
                "reserves": {
                    "reserve0": reserves["reserve0"],
                    "reserve1": reserves["reserve1"],
                    "reserve0_formatted": self.format_amount(reserves["reserve0"], token0_info["decimals"]),
                    "reserve1_formatted": self.format_amount(reserves["reserve1"], token1_info["decimals"]),
                },
                "price": prices,
                "liquidity": liquidity,
            }
        except Exception as e:
            print(f"Error getting pool info: {e}")
            return None

