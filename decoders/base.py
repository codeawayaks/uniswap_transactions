"""
Base decoder class for Uniswap transactions
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from web3 import Web3
from eth_utils import decode_hex, to_checksum_address
from eth_abi import decode


class BaseDecoder(ABC):
    """Base class for Uniswap transaction decoders"""
    
    def __init__(self, w3: Web3):
        self.w3 = w3
        
    @abstractmethod
    def can_decode(self, tx_input: str, to_address: str) -> bool:
        """Check if this decoder can handle the transaction"""
        pass
    
    @abstractmethod
    def decode(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Decode a transaction and return structured data"""
        pass
    
    def get_function_selector(self, tx_input: str) -> str:
        """Extract function selector from transaction input"""
        if len(tx_input) < 10:
            return None
        return tx_input[:10].lower()
    
    def decode_input_data(self, tx_input: str, function_abi: Dict[str, Any]) -> tuple:
        """Decode transaction input data using function ABI"""
        try:
            # Remove function selector (first 4 bytes = 10 hex chars)
            if len(tx_input) < 10:
                return None
            
            encoded_params = tx_input[10:]
            if not encoded_params:
                return None
            
            # Get input types from ABI
            input_types = [inp["type"] for inp in function_abi.get("inputs", [])]
            
            # Decode parameters
            decoded = decode(input_types, decode_hex(encoded_params))
            return decoded
        except Exception as e:
            print(f"Error decoding input data: {e}")
            return None
    
    def parse_transfer_events(self, receipt: Dict[str, Any]) -> list:
        """Parse Transfer events from transaction receipt"""
        transfer_events = []
        transfer_signature = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        
        if not receipt or "logs" not in receipt:
            return transfer_events
        
        for log in receipt["logs"]:
            if len(log.get("topics", [])) < 1:
                continue
            
            # Check if it's a Transfer event (first topic is event signature)
            if log["topics"][0].lower() == transfer_signature:
                try:
                    # Transfer(address indexed from, address indexed to, uint256 value)
                    from_address = to_checksum_address("0x" + log["topics"][1][-40:])
                    to_address = to_checksum_address("0x" + log["topics"][2][-40:])
                    amount = int(log["data"], 16)
                    
                    transfer_events.append({
                        "from": from_address,
                        "to": to_address,
                        "amount": amount,
                        "token": to_checksum_address(log["address"]),
                    })
                except Exception as e:
                    print(f"Error parsing transfer event: {e}")
                    continue
        
        return transfer_events
    
    def format_amount(self, amount: int, decimals: int = 18) -> str:
        """Format token amount with decimals"""
        divisor = 10 ** decimals
        return f"{amount / divisor:.10f}"
    
    def get_token_info(self, token_address: str) -> Dict[str, Any]:
        """Get token information (symbol, decimals, name)"""
        try:
            token_abi = [
                {
                    "constant": True,
                    "inputs": [],
                    "name": "symbol",
                    "outputs": [{"name": "", "type": "string"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"name": "", "type": "uint8"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "name",
                    "outputs": [{"name": "", "type": "string"}],
                    "type": "function"
                },
            ]
            
            contract = self.w3.eth.contract(
                address=to_checksum_address(token_address),
                abi=token_abi
            )
            
            try:
                symbol = contract.functions.symbol().call()
            except:
                symbol = "UNKNOWN"
            
            try:
                decimals = contract.functions.decimals().call()
            except:
                decimals = 18
            
            try:
                name = contract.functions.name().call()
            except:
                name = "Unknown Token"
            
            return {
                "address": to_checksum_address(token_address),
                "symbol": symbol,
                "decimals": decimals,
                "name": name,
            }
        except Exception as e:
            print(f"Error getting token info for {token_address}: {e}")
            return {
                "address": to_checksum_address(token_address),
                "symbol": "UNKNOWN",
                "decimals": 18,
                "name": "Unknown Token",
            }

