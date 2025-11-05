"""
Uniswap V3 Router 2 (V3SwapRouter02) transaction decoder
"""
from typing import Dict, Any, Optional, List
from web3 import Web3
from eth_utils import to_checksum_address, decode_hex
from eth_abi import decode
from decoders.base import BaseDecoder
from decoders.v3 import V3Decoder
from utils.contract_addresses import UNISWAP_V3_ROUTER2


class V3Router2Decoder(BaseDecoder):
    """Decoder for Uniswap V3SwapRouter02 transactions (multicall support)"""
    
    # V3SwapRouter02 function selectors
    FUNCTION_SELECTORS = {
        "0x5ae401dc": "multicall",  # Multicall function
        "0x414bf389": "exactInputSingle",
        "0xdb3e2198": "exactOutputSingle",
        "0xc04b8d59": "exactInput",
        "0xf28cfc8d": "exactOutput",
        "0x04e45aaf": "exactInputSingleV2",
        "0x5023b4df": "exactOutputSingleV2",
        "0xdb3e2198": "exactOutputSingle",
    }
    
    def __init__(self, w3: Web3):
        super().__init__(w3)
        self.v3_decoder = V3Decoder(w3)  # Reuse V3 decoder logic
        self.router_address = UNISWAP_V3_ROUTER2.lower()
    
    def can_decode(self, tx_input: str, to_address: str) -> bool:
        """Check if this is a V3 Router2 transaction"""
        if not tx_input or len(tx_input) < 10:
            return False
        
        if to_address.lower() != self.router_address:
            return False
        
        selector = self.get_function_selector(tx_input)
        return selector in self.FUNCTION_SELECTORS
    
    def decode(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Decode V3 Router2 transaction"""
        if not receipt:
            return {
                "version": "v3_router2",
                "success": False,
                "error": "No receipt available",
            }
        
        if receipt.get("status") != 1:
            return {
                "version": "v3_router2",
                "success": False,
                "error": "Transaction failed",
                "transaction_hash": tx.get("hash"),
            }
        
        tx_input = tx.get("input", "")
        selector = self.get_function_selector(tx_input)
        function_name = self.FUNCTION_SELECTORS.get(selector)
        
        if not function_name:
            return {
                "version": "v3_router2",
                "success": False,
                "error": "Unknown function",
            }
        
        result = {
            "version": "v3_router2",
            "success": True,
            "function": function_name,
            "transaction_hash": tx.get("hash"),
            "block_number": tx.get("blockNumber"),
            "from": to_checksum_address(tx.get("from", "")),
            "to": to_checksum_address(tx.get("to", "")),
        }
        
        # Handle multicall - decode nested calls
        if function_name == "multicall":
            multicall_data = self._decode_multicall(tx_input)
            if multicall_data:
                result["multicall"] = multicall_data
                result["calls"] = []
                
                # Process each call in multicall
                for call_data in multicall_data:
                    decoded_call = self._decode_single_call(call_data, tx, receipt)
                    if decoded_call:
                        result["calls"].append(decoded_call)
                
                # Extract overall swap info from first and last calls
                if result["calls"]:
                    first_call = result["calls"][0]
                    last_call = result["calls"][-1]
                    
                    if "token_in" in first_call and "token_out" in last_call:
                        result.update({
                            "token_in": first_call.get("token_in"),
                            "token_out": last_call.get("token_out"),
                            "token_pair": f"{first_call.get('token_in', {}).get('symbol', '')}/{last_call.get('token_out', {}).get('symbol', '')}",
                        })
                        
                        # Aggregate amounts
                        total_amount_in = sum(c.get("amount_in_actual", 0) for c in result["calls"] if "amount_in_actual" in c)
                        total_amount_out = sum(c.get("amount_out_actual", 0) for c in result["calls"] if "amount_out_actual" in c)
                        
                        if total_amount_in > 0 or total_amount_out > 0:
                            result.update({
                                "amount_in_actual": total_amount_in,
                                "amount_out_actual": total_amount_out,
                            })
        else:
            # Direct swap call - delegate to V3 decoder
            decoded = self.v3_decoder.decode(tx, receipt)
            if decoded.get("success"):
                result.update(decoded)
                result["version"] = "v3_router2"
        
        return result
    
    def _decode_multicall(self, tx_input: str) -> Optional[List[Dict[str, Any]]]:
        """Decode multicall input data"""
        try:
            # Remove function selector (first 10 chars)
            if len(tx_input) < 10:
                return None
            
            encoded_params = tx_input[10:]
            if not encoded_params:
                return None
            
            # Multicall(uint256 deadline, bytes[] calldata data)
            # First decode the array length, then each bytes element
            decoded = decode(['bytes[]'], decode_hex(encoded_params))
            if decoded and len(decoded) > 0:
                calls = []
                for call_data in decoded[0]:
                    calls.append({
                        "data": call_data.hex() if isinstance(call_data, bytes) else call_data,
                    })
                return calls
            return None
        except Exception as e:
            print(f"Error decoding multicall: {e}")
            return None
    
    def _decode_single_call(self, call_data: Dict[str, Any], tx: Dict[str, Any], receipt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Decode a single call within multicall"""
        try:
            data = call_data.get("data", "")
            if isinstance(data, str) and data.startswith("0x"):
                data = data[2:]
            
            if len(data) < 8:  # Need at least 4 bytes for selector
                return None
            
            selector = "0x" + data[:8]
            
            # Check if it's a swap function
            if selector in ["0x414bf389", "0xdb3e2198", "0xc04b8d59", "0xf28cfc8d"]:
                # Create a mock transaction for V3 decoder
                mock_tx = {
                    "input": "0x" + data,
                    "hash": tx.get("hash"),
                    "blockNumber": tx.get("blockNumber"),
                    "from": tx.get("from"),
                    "to": tx.get("to"),
                }
                
                # Use V3 decoder to decode this call
                decoded = self.v3_decoder.decode(mock_tx, receipt)
                return decoded
            
            return {
                "selector": selector,
                "data": "0x" + data,
                "type": "unknown",
            }
        except Exception as e:
            print(f"Error decoding single call: {e}")
            return None

