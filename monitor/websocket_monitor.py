"""
WebSocket-based real-time transaction monitor
"""
import asyncio
import json
import logging
from typing import Callable, Optional, Dict, Any
from web3 import Web3
import websockets
from config import ETHEREUM_WSS_URL, WEBSOCKET_TIMEOUT, RECONNECT_DELAY

logger = logging.getLogger(__name__)


class WebSocketMonitor:
    """Monitor Ethereum transactions via WebSocket"""
    
    def __init__(self, w3: Web3, callback: Callable[[Dict[str, Any]], None]):
        self.w3 = w3
        self.callback = callback
        self.wss_url = ETHEREUM_WSS_URL
        self.running = False
        self.websocket = None
        self.subscription_id = None
    
    async def connect(self):
        """Connect to WebSocket endpoint"""
        try:
            # Log monitoring setup
            from utils.contract_addresses import UNISWAP_ROUTERS
            logger.info("=" * 60)
            logger.info("Uniswap Transaction Monitor - Starting")
            logger.info("=" * 60)
            logger.info(f"Monitoring Uniswap routers:")
            for version, address in UNISWAP_ROUTERS.items():
                if address != "0x0000000000000000000000000000000000000000":  # Skip V4 placeholder
                    logger.info(f"  - {version.upper()}: {address}")
            logger.info("=" * 60)
            
            # Try direct WebSocket connection
            if self.wss_url.startswith("wss://") or self.wss_url.startswith("ws://"):
                # Use open_timeout parameter for websockets 12.0+
                # This is the correct parameter name for connection timeout
                self.websocket = await websockets.connect(
                    self.wss_url,
                    ping_interval=None,
                    open_timeout=WEBSOCKET_TIMEOUT
                )
            else:
                # Use Web3 provider's WebSocket if available
                if hasattr(self.w3.provider, 'ws'):
                    self.websocket = self.w3.provider.ws
                else:
                    raise ValueError("No WebSocket provider available")
            
            logger.info("WebSocket connected successfully")
            return True
        except asyncio.TimeoutError:
            logger.error(f"WebSocket connection timed out after {WEBSOCKET_TIMEOUT} seconds")
            return False
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            return False
    
    async def subscribe_new_blocks(self):
        """Subscribe to new block headers"""
        try:
            # Ethereum JSON-RPC subscription
            subscription = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_subscribe",
                "params": ["newHeads"]
            }
            
            await self.websocket.send(json.dumps(subscription))
            response = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=WEBSOCKET_TIMEOUT
            )
            
            result = json.loads(response)
            if "result" in result:
                self.subscription_id = result["result"]
                logger.info(f"Subscribed to new blocks: {self.subscription_id}")
                return True
            else:
                logger.error(f"Subscription failed: {result}")
                return False
        except Exception as e:
            logger.error(f"Subscription error: {e}")
            return False
    
    async def start(self):
        """Start monitoring"""
        self.running = True
        
        while self.running:
            try:
                if not self.websocket:
                    if not await self.connect():
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue
                
                if not self.subscription_id:
                    if not await self.subscribe_new_blocks():
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue
                
                # Listen for messages
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=WEBSOCKET_TIMEOUT
                    )
                    
                    data = json.loads(message)
                    
                    # Log received message for debugging
                    logger.debug(f"Received WebSocket message: {json.dumps(data, indent=2)}")
                    
                    # Handle subscription messages
                    # Format: {"jsonrpc": "2.0", "method": "eth_subscription", "params": {"subscription": "...", "result": {...}}}
                    if "method" in data and data["method"] == "eth_subscription":
                        if "params" in data and "result" in data["params"]:
                            block_data = data["params"]["result"]
                            block_number = int(block_data.get("number", "0x0"), 16)
                            logger.info(f"Received new block: {block_number}")
                            
                            # Fetch and process block transactions
                            await self._process_block(block_number)
                        else:
                            logger.debug(f"Subscription message without expected structure: {data}")
                    elif "params" in data and "result" in data["params"]:
                        # Fallback for different message formats
                        block_data = data["params"]["result"]
                        if isinstance(block_data, dict) and "number" in block_data:
                            block_number = int(block_data.get("number", "0x0"), 16)
                            logger.info(f"Received new block: {block_number}")
                            await self._process_block(block_number)
                    else:
                        logger.debug(f"Received non-subscription message: {data}")
                
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    logger.debug(f"No messages received in {WEBSOCKET_TIMEOUT} seconds, sending ping to keep connection alive...")
                    if self.websocket:
                        try:
                            await self.websocket.ping()
                        except Exception as ping_error:
                            logger.warning(f"Ping failed: {ping_error}")
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket connection closed, reconnecting...")
                    self.websocket = None
                    self.subscription_id = None
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue
            
            except Exception as e:
                logger.error(f"WebSocket monitor error: {e}")
                self.websocket = None
                self.subscription_id = None
                await asyncio.sleep(RECONNECT_DELAY)
    
    async def _process_block(self, block_number: int):
        """Process transactions in a block"""
        try:
            block = self.w3.eth.get_block(block_number, full_transactions=True)
            
            if not block:
                logger.warning(f"Block {block_number} not found")
                return
            
            if "transactions" not in block:
                logger.debug(f"Block {block_number} has no transactions field")
                return
            
            transactions = block.get("transactions", [])
            logger.info(f"Processing block {block_number} with {len(transactions)} transactions")
            
            # Import here to avoid circular dependency
            from utils.contract_addresses import is_uniswap_router, UNISWAP_ROUTERS
            
            # Log all router addresses we're checking for debugging
            if len(transactions) > 0:
                logger.debug(f"Monitoring for Uniswap routers: {list(UNISWAP_ROUTERS.values())}")
            
            # Enhanced debugging: log transaction details
            sample_addresses = []
            sample_tx_details = []
            uniswap_count = 0
            
            # Method 1: Check transactions to Uniswap routers
            for idx, tx in enumerate(transactions):
                if isinstance(tx, dict):
                    # Check transaction structure
                    tx_hash = tx.get("hash")
                    if tx_hash:
                        # Convert hash to hex if it's a bytes object
                        if hasattr(tx_hash, 'hex'):
                            tx_hash = tx_hash.hex()
                        tx_hash = str(tx_hash)
                    
                    # Check if transaction is to Uniswap router BEFORE processing
                    to_address = tx.get("to")
                    
                    # Debug: log first few transaction details
                    if idx < 3:
                        logger.debug(f"  TX {idx}: hash={tx_hash[:16] if tx_hash else 'N/A'}..., to={to_address}, type={type(to_address)}")
                    
                    if to_address:
                        # Handle different address formats
                        if hasattr(to_address, 'hex'):
                            to_address = to_address.hex()
                        to_address = str(to_address)
                        to_address_lower = to_address.lower()
                        
                        # Sample first 5 unique addresses for debugging
                        if len(sample_addresses) < 5 and to_address_lower not in sample_addresses:
                            sample_addresses.append(to_address_lower)
                            # Also store transaction input for debugging
                            tx_input = tx.get("input", "")
                            if tx_input and len(tx_input) >= 10:
                                selector = tx_input[:10]
                                sample_tx_details.append({
                                    'to': to_address_lower,
                                    'selector': selector,
                                    'hash': tx_hash[:16] if tx_hash else 'N/A'
                                })
                        
                        # Check if it's a Uniswap router
                        is_router = is_uniswap_router(to_address_lower)
                        if idx < 3:
                            logger.debug(f"    Checking {to_address_lower[:20]}...: {is_router}")
                        
                        if is_router:
                            logger.info(f"✓ Found Uniswap transaction to {to_address_lower} (tx: {tx_hash[:16] if tx_hash else 'unknown'}...)")
                            await self._process_transaction(tx, block_number)
                            uniswap_count += 1
                    else:
                        # Contract creation or other edge case
                        if idx < 3:
                            logger.debug(f"  TX {idx}: No 'to' address (contract creation or other)")
            
            # Method 2: Check for Uniswap Swap events using get_logs (much more efficient!)
            # Most Uniswap swaps go through aggregators, so we need to check event logs
            # Flow: Get Block -> Use get_logs filter -> Iterate Logs -> Check Topic0
            if uniswap_count == 0 and len(transactions) > 0:
                logger.debug(f"Checking for Uniswap Swap events in block {block_number} using get_logs...")
                
                # Step 1: Define ALL possible Swap event topic hashes (Topic0)
                # Comprehensive list of Swap event signatures across all DEXs and Uniswap versions
                
                # Calculate all known Swap event signatures dynamically
                swap_signatures = {
                    # Uniswap V2 - Standard format
                    "Swap(address,uint256,uint256,uint256,uint256,address)": "V2",
                    # Uniswap V2 - With indexed parameters (alternative format)
                    "Swap(address indexed,uint256,uint256,uint256,uint256,address indexed)": "V2",
                    # Uniswap V3 - Standard format
                    "Swap(address,address,int256,int256,uint160,uint128,int24)": "V3",
                    # Uniswap V3 - With indexed parameters
                    "Swap(address indexed,address indexed,int256,int256,uint160,uint128,int24)": "V3",
                    # Uniswap V4 - Standard format
                    "Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)": "V4",
                    # Alternative formats with different parameter names (same structure)
                    "Swap(address indexed sender, uint amount0In, uint amount1In, uint amount0Out, uint amount1Out, address indexed to)": "V2",
                    "Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)": "V3",
                }
                
                # Calculate topic hashes for all signatures
                swap_topics = []
                swap_topic_map = {}
                
                for signature, version in swap_signatures.items():
                    topic_hash = Web3.keccak(text=signature).hex()
                    topic_hash_lower = topic_hash.lower()
                    
                    if topic_hash_lower not in swap_topic_map:  # Avoid duplicates
                        swap_topics.append(topic_hash)
                        swap_topic_map[topic_hash_lower] = version
                        logger.debug(f"Added Swap topic: {version} - {topic_hash}")
                
                # Also include user-provided hashes that might be variants
                KNOWN_TOPICS = {
                    "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822": "V2",  # Standard V2
                    "0xd78ad95fa46c994b6551d0112fbc6c4b9c8b9d6292e3b11c6d8800a7854b7696": "V2",  # User provided variant
                    "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67": "V3",  # Standard V3
                    "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f": "V4",  # Standard V4
                    "0xef6b9b96ea78363f131c8e6099221da4a0e57870f503a5263c50a86300f1d589": "V2",  # V2 with indexed
                    "0x2fc839f3c8678efda1534b41348d3b3a4900ad829cb01650b850e4012251acb0": "V2",  # V2 alternative naming
                    "0x5d1df90e3d85b17114d0a0e9bacf691cdba59028b3cdd9f6051d8fb416da1519": "V3",  # V3 alternative naming
                }
                
                # Add known topics to the list
                for topic_hash, version in KNOWN_TOPICS.items():
                    topic_hash_lower = topic_hash.lower()
                    if topic_hash_lower not in swap_topic_map:
                        swap_topics.append(topic_hash)
                        swap_topic_map[topic_hash_lower] = version
                
                # Use the comprehensive list
                SWAP_TOPICS = swap_topics
                
                logger.debug(f"Monitoring {len(SWAP_TOPICS)} Swap event topic hashes")
                logger.debug(f"Swap versions: {set(swap_topic_map.values())}")
                
                try:
                    # Step 2: Create a filter for the specific block and Swap topics
                    # This is MUCH more efficient than checking individual receipts!
                    log_filter = {
                        "fromBlock": block_number,
                        "toBlock": block_number,
                        "topics": [
                            SWAP_TOPICS  # This is an "OR" condition for V2 or V3
                        ]
                    }
                    
                    # Step 3: Get logs using filter (single RPC call instead of hundreds!)
                    loop = asyncio.get_event_loop()
                    logs = await loop.run_in_executor(
                        None,
                        self.w3.eth.get_logs,
                        log_filter
                    )
                    
                    if logs:
                        logger.info(f"Found {len(logs)} Uniswap Swap events in Block {block_number}")
                        
                        # Step 4: Process each log and find corresponding transaction
                        for log in logs:
                            try:
                                # Get transaction hash from log
                                tx_hash = log.get('transactionHash')
                                if not tx_hash:
                                    continue
                                
                                # Convert to string format
                                if hasattr(tx_hash, 'hex'):
                                    tx_hash_str = tx_hash.hex()
                                else:
                                    tx_hash_str = str(tx_hash)
                                
                                # Check Topic0 to determine swap type
                                topics = log.get('topics', [])
                                if not topics or len(topics) == 0:
                                    continue
                                
                                topic0 = topics[0]
                                if hasattr(topic0, 'hex'):
                                    topic0 = topic0.hex()
                                topic0 = str(topic0).lower()
                                
                                # Determine event type
                                event_type = swap_topic_map.get(topic0, "Unknown")
                                
                                # Log unknown topics for debugging
                                if event_type == "Unknown":
                                    logger.warning(f"⚠ Unknown Swap event topic0: {topic0} in TX: {tx_hash_str[:16]}...")
                                    # Show some known topic hashes for reference
                                    known_v2 = [k for k, v in swap_topic_map.items() if v == "V2"][:2]
                                    known_v3 = [k for k, v in swap_topic_map.items() if v == "V3"][:1]
                                    known_v4 = [k for k, v in swap_topic_map.items() if v == "V4"][:1]
                                    if known_v2:
                                        logger.debug(f"   Known V2 topics: {known_v2[0][:20]}...")
                                    if known_v3:
                                        logger.debug(f"   Known V3 topics: {known_v3[0][:20]}...")
                                    if known_v4:
                                        logger.debug(f"   Known V4 topics: {known_v4[0][:20]}...")
                                    logger.debug(f"   Total known Swap topics: {len(swap_topic_map)}")
                                    # Still process it as it matched our filter - might be a variant
                                    event_type = "Swap"  # Generic swap type
                                
                                # Extract Swap event details from log
                                swap_details = await self._extract_swap_details_from_log(log, event_type)
                                
                                logger.info(f"✓ Found Uniswap {event_type} Swap event - TX: {tx_hash_str[:16]}...")
                                if not swap_details:
                                    logger.info(f"  ⚠ Warning: Could not extract swap details from log (pool: {log.get('address', 'N/A')})")
                                else:
                                    if "pool_address" in swap_details:
                                        logger.info(f"  Pool Address: {swap_details.get('pool_address', 'N/A')}")
                                    
                                    # Token Pair Details
                                    if "token_pair" in swap_details:
                                        logger.info(f"  Token Pair: {swap_details['token_pair']}")
                                    if "token_in" in swap_details:
                                        token_in = swap_details["token_in"]
                                        logger.info(f"  Token In: {token_in.get('symbol', 'N/A')} ({token_in.get('address', 'N/A')})")
                                        logger.info(f"    Name: {token_in.get('name', 'N/A')}, Decimals: {token_in.get('decimals', 'N/A')}")
                                    if "token_out" in swap_details:
                                        token_out = swap_details["token_out"]
                                        logger.info(f"  Token Out: {token_out.get('symbol', 'N/A')} ({token_out.get('address', 'N/A')})")
                                        logger.info(f"    Name: {token_out.get('name', 'N/A')}, Decimals: {token_out.get('decimals', 'N/A')}")
                                    
                                    # Transaction Amounts
                                    if "amount_in" in swap_details:
                                        logger.info(f"  Amount In (raw): {swap_details['amount_in']}")
                                    if "amount_in_formatted" in swap_details:
                                        token_in_symbol = swap_details.get("token_in", {}).get("symbol", "")
                                        logger.info(f"  Amount In: {swap_details['amount_in_formatted']} {token_in_symbol}")
                                    if "amount_out" in swap_details:
                                        logger.info(f"  Amount Out (raw): {swap_details['amount_out']}")
                                    if "amount_out_formatted" in swap_details:
                                        token_out_symbol = swap_details.get("token_out", {}).get("symbol", "")
                                        logger.info(f"  Amount Out: {swap_details['amount_out_formatted']} {token_out_symbol}")
                                    # Exchange rate
                                    if "amount_in" in swap_details and "amount_out" in swap_details and swap_details["amount_in"] > 0:
                                        try:
                                            rate = swap_details["amount_out"] / swap_details["amount_in"]
                                            token_in_symbol = swap_details.get("token_in", {}).get("symbol", "TOKEN_IN")
                                            token_out_symbol = swap_details.get("token_out", {}).get("symbol", "TOKEN_OUT")
                                            logger.info(f"  Exchange Rate: 1 {token_in_symbol} = {rate:.10f} {token_out_symbol}")
                                        except:
                                            pass
                                    
                                    # Pool Info
                                    if "pool_info" in swap_details:
                                        pool = swap_details["pool_info"]
                                        logger.info(f"  Pool Address: {pool.get('pool_address', 'N/A')}")
                                        # Reserves
                                        if "reserves" in pool:
                                            reserves = pool["reserves"]
                                            if "token0" in pool:
                                                token0 = pool["token0"]
                                                logger.info(f"  Pool Reserve {token0.get('symbol', 'Token0')}: {reserves.get('reserve0_formatted', reserves.get('reserve0', 'N/A'))}")
                                            if "token1" in pool:
                                                token1 = pool["token1"]
                                                logger.info(f"  Pool Reserve {token1.get('symbol', 'Token1')}: {reserves.get('reserve1_formatted', reserves.get('reserve1', 'N/A'))}")
                                        # Price
                                        if "price" in pool:
                                            price = pool["price"]
                                            if "token0_price_in_token1" in price:
                                                logger.info(f"  Price (Token0/Token1): {price['token0_price_in_token1']}")
                                            if "token1_price_in_token0" in price:
                                                logger.info(f"  Price (Token1/Token0): {price['token1_price_in_token0']}")
                                        # Liquidity
                                        if "liquidity" in pool:
                                            liq = pool["liquidity"]
                                            if isinstance(liq, dict):
                                                logger.info(f"  Liquidity Total: {liq.get('liquidity_formatted', liq.get('total', 'N/A'))}")
                                                if "token0_liquidity" in liq:
                                                    logger.info(f"  Liquidity Token0: {liq['token0_liquidity']}")
                                                if "token1_liquidity" in liq:
                                                    logger.info(f"  Liquidity Token1: {liq['token1_liquidity']}")
                                            else:
                                                logger.info(f"  Liquidity: {pool.get('liquidity_formatted', liq)}")
                                        # Additional V3/V4 info
                                        if "sqrt_price_x96" in pool:
                                            logger.info(f"  Sqrt Price X96: {pool['sqrt_price_x96']}")
                                        if "tick" in pool:
                                            logger.info(f"  Tick: {pool['tick']}")
                                        if "fee" in swap_details:
                                            fee = swap_details.get("fee", 0)
                                            if isinstance(fee, int):
                                                logger.info(f"  Fee: {fee} (0.{fee/10000:.4f}%)")
                                    else:
                                        logger.info(f"  ⚠ Warning: swap_details is empty or missing key fields")
                                
                                # Find the transaction in the block to get full transaction data
                                tx_data = None
                                
                                # Try multiple methods to find the transaction
                                for tx in transactions:
                                    if isinstance(tx, dict):
                                        tx_hash_check = tx.get("hash")
                                        if tx_hash_check:
                                            # Convert to comparable format
                                            if hasattr(tx_hash_check, 'hex'):
                                                tx_hash_check = tx_hash_check.hex()
                                            tx_hash_check = str(tx_hash_check).lower()
                                            
                                            if tx_hash_check == tx_hash_str.lower():
                                                tx_data = tx
                                                break
                                
                                # If not found in block transactions, try fetching receipt directly
                                if not tx_data:
                                    try:
                                        logger.debug(f"Transaction {tx_hash_str[:16]}... not in block transactions, fetching receipt...")
                                        loop = asyncio.get_event_loop()
                                        receipt = await loop.run_in_executor(
                                            None,
                                            self.w3.eth.get_transaction_receipt,
                                            tx_hash_str
                                        )
                                        
                                        if receipt:
                                            # Get transaction from receipt
                                            tx_full = await loop.run_in_executor(
                                                None,
                                                self.w3.eth.get_transaction,
                                                tx_hash_str
                                            )
                                            if tx_full:
                                                tx_data = dict(tx_full)
                                                logger.debug(f"Found transaction via receipt lookup")
                                    except Exception as e:
                                        logger.debug(f"Could not fetch transaction {tx_hash_str[:16]}...: {e}")
                                
                                # If transaction found, process it with swap details
                                if tx_data:
                                    # Add swap details to transaction for enhanced processing
                                    if swap_details:
                                        # Store swap details in transaction for callback
                                        if "swap_details" not in tx_data:
                                            tx_data["swap_details"] = swap_details
                                    
                                    await self._process_transaction(tx_data, block_number)
                                    uniswap_count += 1
                                else:
                                    # Transaction not found - but we have swap details from log
                                    if swap_details:
                                        # Create a minimal transaction structure from swap details
                                        logger.info(f"Processing swap from event log (no transaction found):")
                                        if "pool_address" in swap_details:
                                            logger.info(f"  Pool Address: {swap_details.get('pool_address', 'N/A')}")
                                        
                                        # Token Pair Details
                                        if "token_pair" in swap_details:
                                            logger.info(f"  Token Pair: {swap_details['token_pair']}")
                                        if "token_in" in swap_details:
                                            token_in = swap_details["token_in"]
                                            logger.info(f"  Token In: {token_in.get('symbol', 'N/A')} ({token_in.get('address', 'N/A')})")
                                            logger.info(f"    Name: {token_in.get('name', 'N/A')}, Decimals: {token_in.get('decimals', 'N/A')}")
                                        if "token_out" in swap_details:
                                            token_out = swap_details["token_out"]
                                            logger.info(f"  Token Out: {token_out.get('symbol', 'N/A')} ({token_out.get('address', 'N/A')})")
                                            logger.info(f"    Name: {token_out.get('name', 'N/A')}, Decimals: {token_out.get('decimals', 'N/A')}")
                                        
                                        # Transaction Amounts
                                        if "amount_in" in swap_details:
                                            logger.info(f"  Amount In (raw): {swap_details['amount_in']}")
                                        if "amount_in_formatted" in swap_details:
                                            token_in_symbol = swap_details.get("token_in", {}).get("symbol", "")
                                            logger.info(f"  Amount In: {swap_details['amount_in_formatted']} {token_in_symbol}")
                                        if "amount_out" in swap_details:
                                            logger.info(f"  Amount Out (raw): {swap_details['amount_out']}")
                                        if "amount_out_formatted" in swap_details:
                                            token_out_symbol = swap_details.get("token_out", {}).get("symbol", "")
                                            logger.info(f"  Amount Out: {swap_details['amount_out_formatted']} {token_out_symbol}")
                                        # Exchange rate
                                        if "amount_in" in swap_details and "amount_out" in swap_details and swap_details["amount_in"] > 0:
                                            try:
                                                rate = swap_details["amount_out"] / swap_details["amount_in"]
                                                token_in_symbol = swap_details.get("token_in", {}).get("symbol", "TOKEN_IN")
                                                token_out_symbol = swap_details.get("token_out", {}).get("symbol", "TOKEN_OUT")
                                                logger.info(f"  Exchange Rate: 1 {token_in_symbol} = {rate:.10f} {token_out_symbol}")
                                            except:
                                                pass
                                        
                                        # Pool Info
                                        if "pool_info" in swap_details:
                                            pool = swap_details["pool_info"]
                                            logger.info(f"  Pool Address: {pool.get('pool_address', 'N/A')}")
                                            # Reserves
                                            if "reserves" in pool:
                                                reserves = pool["reserves"]
                                                if "token0" in pool:
                                                    token0 = pool["token0"]
                                                    logger.info(f"  Pool Reserve {token0.get('symbol', 'Token0')}: {reserves.get('reserve0_formatted', reserves.get('reserve0', 'N/A'))}")
                                                if "token1" in pool:
                                                    token1 = pool["token1"]
                                                    logger.info(f"  Pool Reserve {token1.get('symbol', 'Token1')}: {reserves.get('reserve1_formatted', reserves.get('reserve1', 'N/A'))}")
                                            # Price
                                            if "price" in pool:
                                                price = pool["price"]
                                                if "token0_price_in_token1" in price:
                                                    logger.info(f"  Price (Token0/Token1): {price['token0_price_in_token1']}")
                                                if "token1_price_in_token0" in price:
                                                    logger.info(f"  Price (Token1/Token0): {price['token1_price_in_token0']}")
                                            # Liquidity
                                            if "liquidity" in pool:
                                                liq = pool["liquidity"]
                                                if isinstance(liq, dict):
                                                    logger.info(f"  Liquidity Total: {liq.get('liquidity_formatted', liq.get('total', 'N/A'))}")
                                                    if "token0_liquidity" in liq:
                                                        logger.info(f"  Liquidity Token0: {liq['token0_liquidity']}")
                                                    if "token1_liquidity" in liq:
                                                        logger.info(f"  Liquidity Token1: {liq['token1_liquidity']}")
                                                else:
                                                    logger.info(f"  Liquidity: {pool.get('liquidity_formatted', liq)}")
                                            # Additional V3/V4 info
                                            if "sqrt_price_x96" in pool:
                                                logger.info(f"  Sqrt Price X96: {pool['sqrt_price_x96']}")
                                            if "tick" in pool:
                                                logger.info(f"  Tick: {pool['tick']}")
                                            if "fee" in swap_details:
                                                fee = swap_details.get("fee", 0)
                                                if isinstance(fee, int):
                                                    logger.info(f"  Fee: {fee} (0.{fee/10000:.4f}%)")
                                        
                                        # Try to get receipt to process anyway
                                        try:
                                            loop = asyncio.get_event_loop()
                                            receipt = await loop.run_in_executor(
                                                None,
                                                self.w3.eth.get_transaction_receipt,
                                                tx_hash_str
                                            )
                                            if receipt:
                                                # Create minimal tx structure
                                                minimal_tx = {
                                                    "hash": tx_hash_str,
                                                    "to": swap_details.get("pool_address"),
                                                    "from": swap_details.get("sender") if "sender" in swap_details else None,
                                                    "blockNumber": block_number,
                                                }
                                                minimal_tx["swap_details"] = swap_details
                                                await self._process_transaction(minimal_tx, block_number)
                                                uniswap_count += 1
                                        except Exception as e:
                                            logger.debug(f"Could not process swap from log: {e}")
                                    else:
                                        logger.warning(f"Transaction {tx_hash_str[:16]}... not found in block {block_number} transactions")
                                        logger.debug(f"   This may be an internal transaction or the transaction format differs")
                                    
                            except Exception as e:
                                logger.debug(f"Error processing log: {e}")
                                continue
                        
                        if uniswap_count > 0:
                            logger.info(f"Processed {uniswap_count} Uniswap swaps from {len(logs)} Swap events")
                    else:
                        logger.debug(f"No Uniswap Swap events found in Block {block_number}")
                        
                except Exception as e:
                    logger.error(f"Error checking logs for block {block_number}: {e}")
                    # Fallback to receipt checking if get_logs fails
                    logger.debug(f"Falling back to receipt checking method...")
                    # Could implement fallback here if needed
            
            if uniswap_count == 0:
                logger.info(f"Block {block_number} has no Uniswap transactions")
                if len(sample_addresses) > 0:
                    logger.info(f"Sample addresses in block {block_number}: {sample_addresses[:5]}")
                    if sample_tx_details:
                        logger.info(f"Sample transaction details:")
                        for detail in sample_tx_details[:3]:
                            logger.info(f"  To: {detail['to']}, Selector: {detail['selector']}, Hash: {detail['hash']}...")
                
                # Check if any sample addresses match router patterns (partial match)
                if len(sample_addresses) > 0:
                    router_addresses_lower = [addr.lower() for addr in UNISWAP_ROUTERS.values() if addr != "0x0000000000000000000000000000000000000000"]
                    for sample_addr in sample_addresses[:5]:
                        for router_addr in router_addresses_lower:
                            if sample_addr == router_addr:
                                logger.warning(f"⚠ ADDRESS MATCH FOUND but not detected! Sample: {sample_addr}, Router: {router_addr}")
                                logger.warning(f"   This indicates a bug in is_uniswap_router() function!")
            else:
                logger.info(f"Block {block_number} processed {uniswap_count} Uniswap transactions")
        
        except Exception as e:
            logger.error(f"Error processing block {block_number}: {e}", exc_info=True)
    
    async def _process_transaction(self, tx: Dict[str, Any], block_number: int):
        """Process a single transaction"""
        try:
            # Get transaction receipt
            receipt = self.w3.eth.get_transaction_receipt(tx["hash"])
            
            # Call callback
            self.callback({
                "transaction": tx,
                "receipt": receipt,
                "block_number": block_number,
            })
        
        except Exception as e:
            logger.error(f"Error processing transaction {tx.get('hash')}: {e}")
    
    async def _extract_swap_details_from_log(self, log: Dict[str, Any], event_type: str) -> Optional[Dict[str, Any]]:
        """
        Extract token pair, amounts, and pool info from Swap event log
        """
        try:
            from eth_abi import decode
            from eth_utils import to_checksum_address, decode_hex
            from decoders.base import BaseDecoder
            
            topics = log.get("topics", [])
            data = log.get("data", "")
            pool_address = log.get("address", "")
            
            if not topics or not data:
                return None
            
            # Normalize data format - handle both bytes and string
            if isinstance(data, bytes):
                # If bytes, convert to hex string
                data = data.hex()
            if isinstance(data, str) and data.startswith('0x'):
                # Remove 0x prefix for decode_hex
                data = data[2:]
            elif isinstance(data, str):
                # Already hex string without 0x
                pass
            else:
                # Try to convert to hex string
                try:
                    if hasattr(data, 'hex'):
                        data = data.hex()
                    else:
                        data = str(data)
                        if data.startswith('0x'):
                            data = data[2:]
                except:
                    logger.info(f"  ⚠ Could not normalize data format: {type(data)}")
                    return None
            
            # Create a helper class that implements BaseDecoder's abstract methods
            class HelperDecoder(BaseDecoder):
                def can_decode(self, tx_input: str, to_address: str) -> bool:
                    return False  # Not used for event log extraction
                
                def decode(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
                    return {}  # Not used for event log extraction
            
            # Create a temporary decoder instance for helper methods
            temp_decoder = HelperDecoder(self.w3)
            
            swap_details = {
                "pool_address": to_checksum_address(pool_address) if pool_address else None,
                "event_type": event_type,
            }
            
            # Decode based on event type
            # If event_type is "Swap" (generic), try to determine from log structure
            if event_type == "Swap" or event_type == "Unknown":
                # Try to determine version from log structure
                # V2 has 3 topics (event, sender, to), V3 has 3 topics (event, sender, recipient), V4 has 2 topics (event, pool_id)
                if len(topics) == 3:
                    # Try V2 first (most common), then V3
                    try:
                        # Try V2 decoding
                        if data:
                            data_bytes = decode_hex(data)
                            # V2 has 4 uint256s
                            if len(data_bytes) == 128:  # 4 * 32 bytes
                                event_type = "V2"
                            else:
                                # V3 has 5 values: 2 int256, 1 uint160, 1 uint128, 1 int24
                                event_type = "V3"
                    except:
                        # Fallback to V3
                        event_type = "V3"
                elif len(topics) == 2:
                    event_type = "V4"
            
            if event_type == "V2":
                # V2 Swap: Swap(address indexed sender, uint amount0In, uint amount1In, uint amount0Out, uint amount1Out, address indexed to)
                # topics[0] = event signature
                # topics[1] = sender (indexed)
                # topics[2] = to (indexed)
                # data = amount0In, amount1In, amount0Out, amount1Out
                
                if len(topics) >= 3 and data:
                    try:
                        sender = to_checksum_address("0x" + topics[1].hex()[-40:]) if hasattr(topics[1], 'hex') else to_checksum_address("0x" + str(topics[1])[-40:])
                        to_addr = to_checksum_address("0x" + topics[2].hex()[-40:]) if hasattr(topics[2], 'hex') else to_checksum_address("0x" + str(topics[2])[-40:])
                        
                        # Decode data: uint256, uint256, uint256, uint256
                        data_bytes = decode_hex(data)
                        amounts = decode(['uint256', 'uint256', 'uint256', 'uint256'], data_bytes)
                        amount0_in, amount1_in, amount0_out, amount1_out = amounts
                        logger.info(f"  ✓ Decoded V2 swap data: amount0_in={amount0_in}, amount1_in={amount1_in}, amount0_out={amount0_out}, amount1_out={amount1_out}")
                        
                        # Determine token addresses from pool (need to query pool)
                        # For now, we'll get from pool address
                        logger.info(f"  Fetching pool tokens for V2 pool {pool_address}...")
                        token0, token1 = await self._get_pool_tokens(pool_address, "V2")
                        
                        if not token0 or not token1:
                            logger.info(f"  ⚠ Warning: Could not fetch pool tokens for V2 pool {pool_address}")
                            logger.info(f"    token0={token0}, token1={token1}")
                        else:
                            logger.info(f"  ✓ Got pool tokens: token0={token0}, token1={token1}")
                        
                        if token0 and token1:
                            token0_info = temp_decoder.get_token_info(token0)
                            token1_info = temp_decoder.get_token_info(token1)
                            
                            # Determine which token is in/out based on amounts
                            if amount0_in > 0 and amount1_out > 0:
                                token_in = token0
                                token_out = token1
                                amount_in = amount0_in
                                amount_out = amount1_out
                            elif amount1_in > 0 and amount0_out > 0:
                                token_in = token1
                                token_out = token0
                                amount_in = amount1_in
                                amount_out = amount0_out
                            else:
                                # Both directions, use net amounts
                                token_in = token0 if amount0_in > amount0_out else token1
                                token_out = token1 if token_in == token0 else token0
                                amount_in = amount0_in if token_in == token0 else amount1_in
                                amount_out = amount1_out if token_out == token1 else amount0_out
                            
                            swap_details.update({
                                "token_in": temp_decoder.get_token_info(token_in),
                                "token_out": temp_decoder.get_token_info(token_out),
                                "token_pair": f"{token0_info['symbol']}/{token1_info['symbol']}",
                                "amount_in": amount_in,
                                "amount_out": amount_out,
                                "amount_in_formatted": temp_decoder.format_amount(amount_in, token0_info['decimals'] if token_in == token0 else token1_info['decimals']),
                                "amount_out_formatted": temp_decoder.format_amount(amount_out, token1_info['decimals'] if token_out == token1 else token0_info['decimals']),
                            })
                            
                            # Get pool info
                            logger.info(f"  Fetching pool info for V2 pool {pool_address}...")
                            pool_info = await self._get_pool_info_for_address(pool_address, "V2")
                            if pool_info:
                                swap_details["pool_info"] = pool_info
                                logger.info(f"  ✓ Got pool info")
                            else:
                                logger.info(f"  ⚠ Warning: Could not fetch pool info for V2 pool {pool_address}")
                    except Exception as e:
                        logger.info(f"  ⚠ Error in V2 extraction step: {e}")
                        import traceback
                        logger.info(f"  Traceback: {traceback.format_exc()}")
                else:
                    logger.info(f"  ⚠ V2 extraction failed: len(topics)={len(topics)}, has_data={bool(data)}")
            
            elif event_type == "V3":
                # V3 Swap: Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
                # topics[0] = event signature
                # topics[1] = sender (indexed)
                # topics[2] = recipient (indexed)
                # data = amount0, amount1, sqrtPriceX96, liquidity, tick
                
                if len(topics) >= 3 and data:
                    try:
                        sender = to_checksum_address("0x" + topics[1].hex()[-40:]) if hasattr(topics[1], 'hex') else to_checksum_address("0x" + str(topics[1])[-40:])
                        recipient = to_checksum_address("0x" + topics[2].hex()[-40:]) if hasattr(topics[2], 'hex') else to_checksum_address("0x" + str(topics[2])[-40:])
                        
                        # Decode data: int256, int256, uint160, uint128, int24
                        data_bytes = decode_hex(data)
                        amounts_data = decode(['int256', 'int256', 'uint160', 'uint128', 'int24'], data_bytes)
                        amount0, amount1, sqrt_price_x96, liquidity, tick = amounts_data
                        logger.info(f"  ✓ Decoded V3 swap data: amount0={amount0}, amount1={amount1}")
                        
                        # Get tokens from pool
                        logger.info(f"  Fetching pool tokens for V3 pool {pool_address}...")
                        token0, token1 = await self._get_pool_tokens(pool_address, "V3")
                        
                        if not token0 or not token1:
                            logger.info(f"  ⚠ Warning: Could not fetch pool tokens for V3 pool {pool_address}")
                            logger.info(f"    token0={token0}, token1={token1}")
                        else:
                            logger.info(f"  ✓ Got pool tokens: token0={token0}, token1={token1}")
                        
                        if token0 and token1:
                            token0_info = temp_decoder.get_token_info(token0)
                            token1_info = temp_decoder.get_token_info(token1)
                            
                            # In V3, amounts can be negative (one direction)
                            if amount0 > 0 and amount1 < 0:
                                token_in = token0
                                token_out = token1
                                amount_in = amount0
                                amount_out = abs(amount1)
                            elif amount1 > 0 and amount0 < 0:
                                token_in = token1
                                token_out = token0
                                amount_in = amount1
                                amount_out = abs(amount0)
                            else:
                                # Use absolute values
                                token_in = token0
                                token_out = token1
                                amount_in = abs(amount0)
                                amount_out = abs(amount1)
                            
                            swap_details.update({
                                "token_in": temp_decoder.get_token_info(token_in),
                                "token_out": temp_decoder.get_token_info(token_out),
                                "token_pair": f"{token0_info['symbol']}/{token1_info['symbol']}",
                                "amount_in": amount_in,
                                "amount_out": amount_out,
                                "amount_in_formatted": temp_decoder.format_amount(amount_in, token0_info['decimals'] if token_in == token0 else token1_info['decimals']),
                                "amount_out_formatted": temp_decoder.format_amount(amount_out, token1_info['decimals'] if token_out == token1 else token0_info['decimals']),
                                "sqrt_price_x96": sqrt_price_x96,
                                "liquidity": liquidity,
                                "tick": tick,
                            })
                            
                            # Get pool info
                            logger.info(f"  Fetching pool info for V3 pool {pool_address}...")
                            pool_info = await self._get_pool_info_for_address(pool_address, "V3")
                            if pool_info:
                                swap_details["pool_info"] = pool_info
                                logger.info(f"  ✓ Got pool info")
                            else:
                                logger.info(f"  ⚠ Warning: Could not fetch pool info for V3 pool {pool_address}")
                    except Exception as e:
                        logger.info(f"  ⚠ Error in V3 extraction step: {e}")
                        import traceback
                        logger.info(f"  Traceback: {traceback.format_exc()}")
                else:
                    logger.info(f"  ⚠ V3 extraction failed: len(topics)={len(topics)}, has_data={bool(data)}")
            
            elif event_type == "V4":
                # V4 Swap: Swap(bytes32 id, address sender, int128 amount0, int128 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick, uint24 fee)
                # topics[0] = event signature
                # topics[1] = pool id (bytes32, indexed)
                # data = sender, amount0, amount1, sqrtPriceX96, liquidity, tick, fee
                
                if len(topics) >= 2 and data:
                    try:
                        pool_id = topics[1].hex() if hasattr(topics[1], 'hex') else str(topics[1])
                        
                        # Decode data: address, int128, int128, uint160, uint128, int24, uint24
                        data_bytes = decode_hex(data)
                        swap_data = decode(['address', 'int128', 'int128', 'uint160', 'uint128', 'int24', 'uint24'], data_bytes)
                        sender_addr, amount0, amount1, sqrt_price_x96, liquidity, tick, fee = swap_data
                        logger.info(f"  ✓ Decoded V4 swap data: amount0={amount0}, amount1={amount1}, pool_id={pool_id}")
                        
                        swap_details.update({
                            "pool_id": pool_id,
                            "sender": to_checksum_address(sender_addr),
                            "amount0": amount0,
                            "amount1": amount1,
                            "sqrt_price_x96": sqrt_price_x96,
                            "liquidity": liquidity,
                            "tick": tick,
                            "fee": fee,
                        })
                        
                        # V4 pool info would need pool_id lookup - simplified for now
                        # Note: V4 uses pool_id instead of pool_address, so we can't easily fetch tokens/pool info
                        logger.info(f"  ⚠ V4 pools require pool_id lookup - token/pool info not available from event log")
                        if amount0 > 0 and amount1 < 0:
                            swap_details.update({
                                "amount_in": abs(amount0),
                                "amount_out": abs(amount1),
                            })
                        elif amount1 > 0 and amount0 < 0:
                            swap_details.update({
                                "amount_in": abs(amount1),
                                "amount_out": abs(amount0),
                            })
                    except Exception as e:
                        logger.info(f"  ⚠ Error in V4 extraction step: {e}")
                        import traceback
                        logger.info(f"  Traceback: {traceback.format_exc()}")
                else:
                    logger.info(f"  ⚠ V4 extraction failed: len(topics)={len(topics)}, has_data={bool(data)}")
            
            # Log what we extracted
            if swap_details and len(swap_details) > 2:  # More than just pool_address and event_type
                logger.info(f"  ✓ Successfully extracted swap details")
            elif swap_details:
                logger.info(f"  ⚠ Warning: Only extracted basic info (pool_address, event_type)")
            
            return swap_details
            
        except Exception as e:
            logger.info(f"Error extracting swap details from log: {e}")
            logger.info(f"  Log address: {log.get('address', 'N/A')}, Event type: {event_type}")
            logger.info(f"  Topics count: {len(log.get('topics', []))}, Has data: {bool(log.get('data', ''))}")
            import traceback
            logger.info(f"  Traceback: {traceback.format_exc()}")
            return None
    
    async def _get_pool_tokens(self, pool_address: str, version: str) -> tuple:
        """Get token0 and token1 addresses from pool contract"""
        try:
            loop = asyncio.get_event_loop()
            
            if version == "V2":
                from utils.abi_loader import V2_POOL_ABI
                contract = self.w3.eth.contract(
                    address=pool_address,
                    abi=V2_POOL_ABI
                )
                token0 = await loop.run_in_executor(None, contract.functions.token0().call)
                token1 = await loop.run_in_executor(None, contract.functions.token1().call)
                return token0, token1
            elif version == "V3":
                from utils.abi_loader import V3_POOL_ABI
                contract = self.w3.eth.contract(
                    address=pool_address,
                    abi=V3_POOL_ABI
                )
                token0 = await loop.run_in_executor(None, contract.functions.token0().call)
                token1 = await loop.run_in_executor(None, contract.functions.token1().call)
                return token0, token1
            
            return None, None
        except Exception as e:
            logger.info(f"Error getting pool tokens for {pool_address} ({version}): {e}")
            return None, None
    
    async def _get_pool_info_for_address(self, pool_address: str, version: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive pool information"""
        try:
            from decoders.base import BaseDecoder
            from pool.v2_pool import V2Pool
            from pool.v3_pool import V3Pool
            
            # Create a helper class that implements BaseDecoder's abstract methods
            class HelperDecoder(BaseDecoder):
                def can_decode(self, tx_input: str, to_address: str) -> bool:
                    return False  # Not used for pool info
                
                def decode(self, tx: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
                    return {}  # Not used for pool info
            
            temp_decoder = HelperDecoder(self.w3)
            loop = asyncio.get_event_loop()
            
            if version == "V2":
                pool_querier = V2Pool(self.w3)
                reserves = await loop.run_in_executor(None, pool_querier.get_reserves, pool_address)
                if reserves:
                    token0_info = temp_decoder.get_token_info(reserves["token0"])
                    token1_info = temp_decoder.get_token_info(reserves["token1"])
                    
                    prices = await loop.run_in_executor(
                        None,
                        pool_querier.calculate_price,
                        reserves["reserve0"],
                        reserves["reserve1"],
                        token0_info["decimals"],
                        token1_info["decimals"]
                    )
                    
                    liquidity = await loop.run_in_executor(
                        None,
                        pool_querier.calculate_liquidity,
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
                            "reserve0_formatted": temp_decoder.format_amount(reserves["reserve0"], token0_info["decimals"]),
                            "reserve1_formatted": temp_decoder.format_amount(reserves["reserve1"], token1_info["decimals"]),
                        },
                        "price": prices,
                        "liquidity": liquidity,
                    }
            
            elif version == "V3":
                pool_querier = V3Pool(self.w3)
                pool_state = await loop.run_in_executor(None, pool_querier.get_pool_state, pool_address)
                if pool_state:
                    token0_info = temp_decoder.get_token_info(pool_state["token0"])
                    token1_info = temp_decoder.get_token_info(pool_state["token1"])
                    
                    prices = await loop.run_in_executor(
                        None,
                        pool_querier.calculate_price,
                        pool_state["sqrtPriceX96"],
                        token0_info["decimals"],
                        token1_info["decimals"]
                    )
                    
                    return {
                        "pool_address": pool_address,
                        "token0": token0_info,
                        "token1": token1_info,
                        "sqrt_price_x96": pool_state["sqrtPriceX96"],
                        "liquidity": pool_state["liquidity"],
                        "tick": pool_state["tick"],
                        "price": prices,
                        "liquidity_formatted": temp_decoder.format_amount(pool_state["liquidity"], 18),
                    }
            
            return None
        except Exception as e:
            logger.info(f"Error getting pool info for {pool_address} ({version}): {e}")
            return None
    
    async def stop(self):
        """Stop monitoring"""
        self.running = False
        if self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
        self.websocket = None
        self.subscription_id = None

