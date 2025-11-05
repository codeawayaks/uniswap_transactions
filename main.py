"""
Main entry point for Uniswap transaction decoder
"""
import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import Dict, Any
from web3 import Web3
from config import ETHEREUM_RPC_URL, BACKUP_RPC_URLS, OUTPUT_DIR, LOG_LEVEL
from utils.contract_addresses import is_uniswap_router, get_uniswap_version
from decoders.v2 import V2Decoder
from decoders.v3 import V3Decoder
from decoders.v3_router2 import V3Router2Decoder
from decoders.v4 import V4Decoder
from monitor.websocket_monitor import WebSocketMonitor
from monitor.polling_monitor import PollingMonitor
import os
from typing import Optional

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UniswapDecoder:
    """Main decoder coordinator"""
    
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.decoders = {
            "v2": V2Decoder(w3),
            "v3": V3Decoder(w3),
            "v3_router2": V3Router2Decoder(w3),
            "v4": V4Decoder(w3),
        }
        self.output_dir = OUTPUT_DIR
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
    
    def decode_transaction(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Decode a Uniswap transaction with comprehensive error handling"""
        try:
            # Validate transaction data
            if not tx or not isinstance(tx, dict):
                logger.debug("Invalid transaction data")
                return None
            
            tx_hash = tx.get("hash")
            if not tx_hash:
                logger.debug("Transaction missing hash")
                return None
            
            to_address = tx.get("to", "").lower()
            
            # Check if transaction is to a Uniswap router
            if not to_address:
                logger.debug(f"Transaction {tx_hash} has no 'to' address (contract creation)")
                return None
            
            if not is_uniswap_router(to_address):
                return None
            
            # Get Uniswap version
            version = get_uniswap_version(to_address)
            if not version:
                logger.warning(f"Unknown Uniswap router: {to_address}")
                return None
            
            # Get transaction input early for validation and Universal Router fallback
            tx_input = tx.get("input", "")
            if not tx_input or len(tx_input) < 10:
                logger.debug(f"Transaction {tx_hash} has invalid input data")
                return None
            
            # Get appropriate decoder
            decoder = self.decoders.get(version)
            is_universal_router_fallback = False
            
            if not decoder:
                # For Universal Router, try V3 and V2 decoders as fallback
                # Universal Router uses execute() which can call V2/V3 router functions
                if version == "universal":
                    logger.debug(f"Universal Router transaction detected, checking function selectors...")
                    is_universal_router_fallback = True
                    
                    # Extract function selector
                    selector = tx_input[:10].lower() if len(tx_input) >= 10 else None
                    if not selector:
                        logger.warning(f"Universal Router transaction {tx_hash} has invalid selector")
                        return None
                    
                    # Universal Router uses execute() function with selector 0x24856bc3
                    # This contains commands that can execute V2/V3 swaps
                    universal_router_execute = "0x24856bc3"
                    
                    if selector == universal_router_execute:
                        logger.debug(f"Universal Router execute() call detected, will decode from receipt events")
                        # Use V3 Router2 decoder as it handles multicall-style commands
                        decoder = self.decoders.get("v3_router2")
                        if decoder:
                            version = "universal"  # Keep as universal to track it
                            logger.info(f"Universal Router execute() transaction detected, using V3 Router2 decoder")
                        else:
                            logger.warning(f"Universal Router transaction {tx_hash} could not be decoded (no V3 Router2 decoder)")
                            return None
                    else:
                        # Check if selector matches any known Uniswap function (legacy support)
                        for fallback_version in ["v3_router2", "v3", "v2"]:
                            fallback_decoder = self.decoders.get(fallback_version)
                            if fallback_decoder and hasattr(fallback_decoder, 'FUNCTION_SELECTORS'):
                                if selector in fallback_decoder.FUNCTION_SELECTORS:
                                    logger.info(f"Universal Router transaction matched {fallback_version} selector, using {fallback_version} decoder")
                                    decoder = fallback_decoder
                                    version = fallback_version
                                    break
                        
                        # If no match, try to decode anyway with V3 Router2
                        if not decoder:
                            logger.debug(f"Universal Router transaction {tx_hash} selector {selector} not in known selectors, attempting V3 Router2 decoder...")
                            decoder = self.decoders.get("v3_router2")
                            if decoder:
                                version = "universal"
                            else:
                                logger.warning(f"Universal Router transaction {tx_hash} could not be decoded")
                                return None
                else:
                    logger.warning(f"No decoder available for version: {version}")
                    return None
            
            # Check if decoder can handle this transaction
            # Skip address check for Universal Router fallback decoders (already validated by selector)
            if not is_universal_router_fallback and not decoder.can_decode(tx_input, to_address):
                logger.debug(f"Decoder {version} cannot decode transaction {tx_hash}")
                return None
            
            # Validate receipt
            if not receipt:
                logger.warning(f"Transaction {tx_hash} has no receipt")
                return {
                    "version": version,
                    "success": False,
                    "error": "No receipt available",
                    "transaction_hash": tx_hash,
                }
            
            # Handle failed transactions
            if receipt.get("status") == 0:
                logger.debug(f"Transaction {tx_hash} failed")
                return {
                    "version": version,
                    "success": False,
                    "error": "Transaction failed on-chain",
                    "transaction_hash": tx_hash,
                    "block_number": tx.get("blockNumber"),
                }
            
            # Decode transaction
            try:
                decoded = decoder.decode(tx, receipt)
                
                # Validate decoded result
                if not decoded:
                    logger.warning(f"Decoder returned None for transaction {tx_hash}")
                    return None
                
                # Ensure transaction hash is present
                if "transaction_hash" not in decoded:
                    decoded["transaction_hash"] = tx_hash
                
                return decoded
            
            except Exception as decode_error:
                logger.error(f"Error decoding transaction {tx_hash}: {decode_error}", exc_info=True)
                return {
                    "version": version,
                    "success": False,
                    "error": f"Decoding error: {str(decode_error)}",
                    "transaction_hash": tx_hash,
                    "block_number": tx.get("blockNumber"),
                }
        
        except Exception as e:
            logger.error(f"Unexpected error processing transaction: {e}", exc_info=True)
            return None
    
    def format_output(self, decoded: Dict[str, Any]) -> str:
        """Format decoded transaction for output"""
        output = {
            "timestamp": datetime.utcnow().isoformat(),
            "decoded": decoded,
        }
        return json.dumps(output, indent=2, default=str)
    
    def save_output(self, decoded: Dict[str, Any], tx_hash: str):
        """Save decoded transaction to file"""
        try:
            filename = f"{tx_hash}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            output = self.format_output(decoded)
            
            with open(filepath, 'w') as f:
                f.write(output)
            
            logger.info(f"Saved decoded transaction to {filepath}")
        except Exception as e:
            logger.error(f"Error saving output: {e}")
    
    def print_summary(self, decoded: Dict[str, Any]):
        """Print human-readable summary with comprehensive analysis"""
        if not decoded.get("success"):
            print(f"\n❌ Failed to decode: {decoded.get('error', 'Unknown error')}")
            return
        
        print(f"\n{'='*60}")
        print(f"Uniswap {decoded.get('version', 'unknown').upper()} Transaction")
        if decoded.get("source") == "event_log":
            print(f"  (Extracted from Swap Event Log)")
        print(f"{'='*60}")
        print(f"Transaction Hash: {decoded.get('transaction_hash', 'N/A')}")
        print(f"Block Number: {decoded.get('block_number', 'N/A')}")
        if decoded.get('function'):
            print(f"Function: {decoded['function']}")
        
        # Token Pair Details
        if "token_pair" in decoded:
            print(f"\n{'─'*60}")
            print(f"Token Pair Details:")
            print(f"{'─'*60}")
            print(f"Pair: {decoded['token_pair']}")
            
            if "token_in" in decoded:
                token_in = decoded["token_in"]
                print(f"\nToken In:")
                print(f"  Symbol: {token_in.get('symbol', 'N/A')}")
                print(f"  Address: {token_in.get('address', 'N/A')}")
                print(f"  Name: {token_in.get('name', 'N/A')}")
                print(f"  Decimals: {token_in.get('decimals', 'N/A')}")
            
            if "token_out" in decoded:
                token_out = decoded["token_out"]
                print(f"\nToken Out:")
                print(f"  Symbol: {token_out.get('symbol', 'N/A')}")
                print(f"  Address: {token_out.get('address', 'N/A')}")
                print(f"  Name: {token_out.get('name', 'N/A')}")
                print(f"  Decimals: {token_out.get('decimals', 'N/A')}")
        
        # Transaction Amounts
        if "amount_in_formatted" in decoded or "amount_out_formatted" in decoded:
            print(f"\n{'─'*60}")
            print(f"Transaction Amounts:")
            print(f"{'─'*60}")
            if "amount_in" in decoded:
                print(f"Amount In (raw): {decoded['amount_in']}")
            if "amount_in_formatted" in decoded:
                token_in_symbol = decoded.get("token_in", {}).get("symbol", "")
                print(f"Amount In: {decoded['amount_in_formatted']} {token_in_symbol}")
            
            if "amount_out" in decoded:
                print(f"Amount Out (raw): {decoded['amount_out']}")
            if "amount_out_formatted" in decoded:
                token_out_symbol = decoded.get("token_out", {}).get("symbol", "")
                print(f"Amount Out: {decoded['amount_out_formatted']} {token_out_symbol}")
            
            # Calculate exchange rate if both amounts available
            if "amount_in" in decoded and "amount_out" in decoded and decoded["amount_in"] > 0:
                try:
                    rate = decoded["amount_out"] / decoded["amount_in"]
                    token_in_symbol = decoded.get("token_in", {}).get("symbol", "TOKEN_IN")
                    token_out_symbol = decoded.get("token_out", {}).get("symbol", "TOKEN_OUT")
                    print(f"Exchange Rate: 1 {token_in_symbol} = {rate:.10f} {token_out_symbol}")
                except:
                    pass
        
        # Pool Information
        if "pool_info" in decoded:
            pool = decoded["pool_info"]
            print(f"\n{'─'*60}")
            print(f"Pool Information:")
            print(f"{'─'*60}")
            print(f"Pool Address: {pool.get('pool_address', 'N/A')}")
            
            # Token amounts in pool
            if "reserves" in pool:
                reserves = pool["reserves"]
                print(f"\nPool Reserves:")
                if "token0" in pool:
                    token0 = pool["token0"]
                    print(f"  {token0.get('symbol', 'Token0')}: {reserves.get('reserve0_formatted', reserves.get('reserve0', 'N/A'))}")
                if "token1" in pool:
                    token1 = pool["token1"]
                    print(f"  {token1.get('symbol', 'Token1')}: {reserves.get('reserve1_formatted', reserves.get('reserve1', 'N/A'))}")
            
            # Price Information
            if "price" in pool:
                price = pool["price"]
                print(f"\nPrice:")
                if "token0_price_in_token1" in price:
                    print(f"  Token0 Price: {price['token0_price_in_token1']}")
                if "token1_price_in_token0" in price:
                    print(f"  Token1 Price: {price['token1_price_in_token0']}")
                if "sqrt_price_x96" in pool:
                    print(f"  Sqrt Price X96: {pool['sqrt_price_x96']}")
            
            # Liquidity Information
            if "liquidity" in pool:
                liq = pool["liquidity"]
                if isinstance(liq, dict):
                    print(f"\nLiquidity:")
                    print(f"  Total: {liq.get('liquidity_formatted', liq.get('total', 'N/A'))}")
                    if "token0_liquidity" in liq:
                        print(f"  Token0: {liq['token0_liquidity']}")
                    if "token1_liquidity" in liq:
                        print(f"  Token1: {liq['token1_liquidity']}")
                else:
                    print(f"\nLiquidity: {pool.get('liquidity_formatted', liq)}")
            
            # Additional V3/V4 info
            if "tick" in pool:
                print(f"  Tick: {pool['tick']}")
            if "fee" in decoded:
                fee = decoded.get("fee", 0)
                if isinstance(fee, int):
                    print(f"  Fee: {fee} (0.{fee/10000:.4f}%)")
        
        print(f"{'='*60}\n")


def get_web3_connection() -> Web3:
    """Get Web3 connection with fallback"""
    urls = [ETHEREUM_RPC_URL] + BACKUP_RPC_URLS
    
    for url in urls:
        try:
            w3 = Web3(Web3.HTTPProvider(url))
            if w3.is_connected():
                logger.info(f"Connected to {url}")
                return w3
        except Exception as e:
            logger.warning(f"Failed to connect to {url}: {e}")
            continue
    
    raise ConnectionError("Failed to connect to any Ethereum RPC endpoint")


def transaction_callback(decoder: UniswapDecoder):
    """Callback for processing transactions with error handling"""
    def callback(data: Dict[str, Any]):
        try:
            tx = data.get("transaction")
            receipt = data.get("receipt")
            
            if not tx:
                logger.warning("Callback received data without transaction")
                return
            
            tx_hash = tx.get("hash", "unknown")
            
            # Check if we have swap details extracted from event log
            swap_details = tx.get("swap_details")
            
            # Handle missing receipt gracefully
            if not receipt:
                logger.warning(f"Transaction {tx_hash} has no receipt, attempting to fetch...")
                try:
                    receipt = decoder.w3.eth.get_transaction_receipt(tx_hash)
                except Exception as e:
                    logger.error(f"Failed to fetch receipt for {tx_hash}: {e}")
                    # If we have swap_details, we can still process it
                    if swap_details:
                        _process_swap_details(decoder, swap_details, tx_hash, tx.get("blockNumber"))
                    return
            
            # Decode transaction
            decoded = decoder.decode_transaction(tx, receipt)
            
            # If decoding failed but we have swap details, use those
            if not decoded and swap_details:
                decoded = _create_decoded_from_swap_details(swap_details, tx_hash, tx.get("blockNumber"))
            
            if decoded:
                try:
                    # Enhance decoded data with swap details if available
                    if swap_details:
                        # Merge swap details into decoded result
                        if "pool_info" not in decoded and "pool_info" in swap_details:
                            decoded["pool_info"] = swap_details["pool_info"]
                        if "token_pair" not in decoded and "token_pair" in swap_details:
                            decoded["token_pair"] = swap_details["token_pair"]
                        if "amount_in_formatted" not in decoded and "amount_in_formatted" in swap_details:
                            decoded["amount_in_formatted"] = swap_details["amount_in_formatted"]
                        if "amount_out_formatted" not in decoded and "amount_out_formatted" in swap_details:
                            decoded["amount_out_formatted"] = swap_details["amount_out_formatted"]
                    
                    decoder.print_summary(decoded)
                    decoder.save_output(decoded, tx_hash)
                except Exception as e:
                    logger.error(f"Error processing decoded transaction {tx_hash}: {e}")
        
        except Exception as e:
            logger.error(f"Error in transaction callback: {e}", exc_info=True)
    
    return callback


def _create_decoded_from_swap_details(swap_details: Dict[str, Any], tx_hash: str, block_number: Any) -> Dict[str, Any]:
    """Create a decoded transaction structure from swap details extracted from event log"""
    return {
        "version": swap_details.get("event_type", "Swap").lower(),
        "success": True,
        "transaction_hash": tx_hash,
        "block_number": block_number,
        "token_pair": swap_details.get("token_pair"),
        "token_in": swap_details.get("token_in"),
        "token_out": swap_details.get("token_out"),
        "amount_in": swap_details.get("amount_in"),
        "amount_out": swap_details.get("amount_out"),
        "amount_in_formatted": swap_details.get("amount_in_formatted"),
        "amount_out_formatted": swap_details.get("amount_out_formatted"),
        "pool_info": swap_details.get("pool_info"),
        "pool_address": swap_details.get("pool_address"),
        "source": "event_log"  # Mark as extracted from event log
    }


def _process_swap_details(decoder: UniswapDecoder, swap_details: Dict[str, Any], tx_hash: str, block_number: Any):
    """Process swap details directly when transaction decoding fails"""
    try:
        decoded = _create_decoded_from_swap_details(swap_details, tx_hash, block_number)
        decoder.print_summary(decoded)
        decoder.save_output(decoded, tx_hash)
    except Exception as e:
        logger.error(f"Error processing swap details for {tx_hash}: {e}")


async def run_websocket_monitor(decoder: UniswapDecoder, w3: Web3):
    """Run WebSocket monitor"""
    callback = transaction_callback(decoder)
    monitor = WebSocketMonitor(w3, callback)
    
    try:
        await monitor.start()
    except KeyboardInterrupt:
        logger.info("Stopping WebSocket monitor...")
        await monitor.stop()


def run_polling_monitor(decoder: UniswapDecoder, w3: Web3):
    """Run polling monitor"""
    callback = transaction_callback(decoder)
    monitor = PollingMonitor(w3, callback)
    
    try:
        monitor.start()
    except KeyboardInterrupt:
        logger.info("Stopping polling monitor...")
        monitor.stop()


def main():
    """Main entry point"""
    try:
        # Connect to Ethereum
        w3 = get_web3_connection()
        
        # Initialize decoder
        decoder = UniswapDecoder(w3)
        
        # Check command line arguments
        use_websocket = True
        if len(sys.argv) > 1:
            if sys.argv[1] == "--polling":
                use_websocket = False
        
        logger.info("Starting Uniswap transaction decoder...")
        logger.info(f"Output directory: {OUTPUT_DIR}")
        
        if use_websocket:
            logger.info("Using WebSocket monitoring (fallback to polling if WebSocket fails)")
            try:
                asyncio.run(run_websocket_monitor(decoder, w3))
            except Exception as e:
                logger.warning(f"WebSocket failed, falling back to polling: {e}")
                run_polling_monitor(decoder, w3)
        else:
            logger.info("Using polling monitoring")
            run_polling_monitor(decoder, w3)
    
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

