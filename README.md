# Uniswap Transaction Decoder

A comprehensive Python tool for decoding and analyzing Uniswap swap transactions in real-time from Ethereum nodes. Supports Uniswap V2, V3, V3 Router 2, and V4 protocols.

## Features

- **Real-time Monitoring**: WebSocket and polling-based monitoring of Ethereum transactions
- **Multi-Version Support**: Decodes transactions from Uniswap V2, V3, V3 Router 2, and V4
- **Comprehensive Analysis**: Extracts token pairs, amounts, pool information, prices, and liquidity
- **Pool Queries**: Queries pool contracts for real-time liquidity and price data
- **Error Handling**: Robust error handling for failed transactions and edge cases
- **Multi-hop Swaps**: Supports complex multi-hop swap paths

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd uniswap_transactions
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your RPC endpoints
```

## Configuration

Edit `.env` file or set environment variables:

```env
# Ethereum RPC Configuration
ETHEREUM_RPC_URL=https://eth.llamarpc.com
ETHEREUM_WSS_URL=wss://eth.llamarpc.com

# Monitoring Configuration
BLOCK_CONFIRMATIONS=12
POLLING_INTERVAL=12
WEBSOCKET_TIMEOUT=30
RECONNECT_DELAY=5

# Output Configuration
OUTPUT_DIR=output
LOG_LEVEL=INFO
```

## Usage

### Basic Usage

Run the decoder with default settings (WebSocket with polling fallback):

```bash
python main.py
```

### Polling Mode Only

Use polling mode instead of WebSocket:

```bash
python main.py --polling
```

### Programmatic Usage

```python
from web3 import Web3
from main import UniswapDecoder

# Connect to Ethereum
w3 = Web3(Web3.HTTPProvider("https://eth.llamarpc.com"))

# Initialize decoder
decoder = UniswapDecoder(w3)

# Decode a transaction
tx = w3.eth.get_transaction("0x...")
receipt = w3.eth.get_transaction_receipt("0x...")
result = decoder.decode_transaction(tx, receipt)

if result:
    print(result)
```

## Supported Uniswap Versions

### Uniswap V2
- `swapExactTokensForTokens`
- `swapTokensForExactTokens`
- `swapExactETHForTokens`
- `swapETHForExactTokens`
- Fee-on-transfer token variants

### Uniswap V3
- `exactInputSingle`
- `exactOutputSingle`
- `exactInput` (multi-hop)
- `exactOutput` (multi-hop)

### Uniswap V3 Router 2
- `multicall` with nested swap calls
- All V3 swap functions
- Complex routing scenarios

### Uniswap V4
- `swap` with hooks support
- Flash accounting operations
- Custom hook implementations
- Pool key extraction

## Output Format

The decoder outputs structured JSON data with the following structure:

```json
{
  "timestamp": "2024-01-01T00:00:00",
  "decoded": {
    "version": "v3",
    "success": true,
    "function": "exactInputSingle",
    "transaction_hash": "0x...",
    "block_number": 12345678,
    "token_in": {
      "address": "0x...",
      "symbol": "USDC",
      "decimals": 6,
      "name": "USD Coin"
    },
    "token_out": {
      "address": "0x...",
      "symbol": "WETH",
      "decimals": 18,
      "name": "Wrapped Ether"
    },
    "token_pair": "USDC/WETH",
    "amount_in_actual": 1000000,
    "amount_out_actual": 500000000000000000,
    "amount_in_formatted": "1.0000000000",
    "amount_out_formatted": "0.5000000000",
    "pool_info": {
      "pool_address": "0x...",
      "fee": 3000,
      "price": {
        "token1_price_in_token0": 2000.0,
        "token0_price_in_token1": 0.0005
      },
      "liquidity": {
        "liquidity": 1000000000000000000,
        "liquidity_formatted": 1.0
      }
    }
  }
}
```

## Project Structure

```
uniswap_transactions/
├── main.py                 # Main entry point
├── config.py               # Configuration management
├── requirements.txt        # Python dependencies
├── decoders/               # Transaction decoders
│   ├── base.py            # Base decoder class
│   ├── v2.py              # V2 decoder
│   ├── v3.py              # V3 decoder
│   ├── v3_router2.py      # V3 Router 2 decoder
│   └── v4.py              # V4 decoder
├── monitor/                # Real-time monitoring
│   ├── websocket_monitor.py
│   └── polling_monitor.py
├── pool/                   # Pool query modules
│   ├── v2_pool.py
│   ├── v3_pool.py
│   └── v4_pool.py
├── utils/                  # Utilities
│   ├── abi_loader.py      # ABI management
│   └── contract_addresses.py
└── output/                 # Decoded transaction outputs
```

## Error Handling

The decoder handles various edge cases:

- **Failed Transactions**: Detects and reports failed transactions
- **Missing Receipts**: Attempts to fetch receipts when missing
- **Invalid Input Data**: Gracefully handles malformed transaction data
- **Multi-hop Swaps**: Correctly decodes complex routing paths
- **Custom Hooks**: Supports V4 custom hook implementations
- **Network Errors**: Automatic reconnection and fallback mechanisms

## Limitations

- V4 support requires the actual PoolManager address to be configured
- Some V4 features may need updates based on final protocol specifications
- Pool address calculation for V3 uses placeholder init code hash
- WebSocket connections depend on provider support

## Contributing

Contributions are welcome! Please ensure:

1. Code follows PEP 8 style guidelines
2. All new features include error handling
3. Tests are added for new functionality
4. Documentation is updated

## License

[Add your license here]

## Support

For issues and questions, please open an issue on the repository.

