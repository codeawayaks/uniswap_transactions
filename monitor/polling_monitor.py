"""
Polling-based transaction monitor (fallback)
"""
import time
import logging
from typing import Callable, Optional
from web3 import Web3
from config import POLLING_INTERVAL

logger = logging.getLogger(__name__)


class PollingMonitor:
    """Monitor Ethereum transactions via polling"""
    
    def __init__(self, w3: Web3, callback: Callable[[dict], None]):
        self.w3 = w3
        self.callback = callback
        self.running = False
        self.last_block = None
        self.polling_interval = POLLING_INTERVAL
    
    def start(self):
        """Start polling for new blocks"""
        self.running = True
        
        # Get current block as starting point
        try:
            self.last_block = self.w3.eth.block_number
            logger.info(f"Starting polling from block {self.last_block}")
        except Exception as e:
            logger.error(f"Error getting initial block: {e}")
            self.last_block = None
        
        while self.running:
            try:
                current_block = self.w3.eth.block_number
                
                if self.last_block is None:
                    self.last_block = current_block
                    time.sleep(self.polling_interval)
                    continue
                
                # Process blocks from last_block + 1 to current_block
                if current_block > self.last_block:
                    for block_num in range(self.last_block + 1, current_block + 1):
                        self._process_block(block_num)
                    
                    self.last_block = current_block
                
                time.sleep(self.polling_interval)
            
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(self.polling_interval)
    
    def _process_block(self, block_number: int):
        """Process transactions in a block"""
        try:
            block = self.w3.eth.get_block(block_number, full_transactions=True)
            
            if not block or "transactions" not in block:
                return
            
            # Import here to avoid circular dependency
            from utils.contract_addresses import is_uniswap_router
            
            uniswap_count = 0
            for tx in block["transactions"]:
                if isinstance(tx, dict):
                    to_address = tx.get("to")
                    if to_address and is_uniswap_router(to_address):
                        self._process_transaction(tx, block_number)
                        uniswap_count += 1
            
            if uniswap_count > 0:
                logger.debug(f"Block {block_number} processed {uniswap_count} Uniswap transactions")
        
        except Exception as e:
            logger.error(f"Error processing block {block_number}: {e}")
    
    def _process_transaction(self, tx: dict, block_number: int):
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
    
    def stop(self):
        """Stop polling"""
        self.running = False

