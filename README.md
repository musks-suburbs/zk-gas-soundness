# zk-gas-soundness

## Overview
**zk-gas-soundness** is a CLI tool that monitors gas fee soundness by comparing the **base fee per gas** (EIP-1559) against the **current gas price** reported by an RPC node.  
It provides fast insight into network fee health and can detect anomalies or congestion across EVM-compatible chains, including those used by **Aztec**, **Zama**, and other zk-rollup systems.

### Getting Started
1. Clone the repository  
   `git clone https://github.com/musks-suburbs/zk-gas-soundness.git`

2. Install dependencies  
   `pip install -r requirements.txt`

3. Basic usage example  
   `python app.py --rpc https://mainnet.infura.io/v3/<API_KEY> --tx 0x...`

## Features
- Fetch base fee, gas price, and block number  
- Compute the gas price to base fee ratio  
- Warn when gas prices deviate abnormally  
- Works with Ethereum, L2s, and testnets  
- JSON output for integration with dashboards or CI/CD pipelines  

## Prerequisites  
- Python 3.9+ (tested)  
- web3.py version 6.x  
- Access to an Ethereum-compatible RPC endpoint (mainnet or supported L2)  
- Optional: blobBaseFee support for EIP-4844 networks  

## Installation
1. Requires Python 3.9+  
2. Install dependencies:
   pip install web3
3. Optionally set your RPC endpoint:
   export RPC_URL=https://mainnet.infura.io/v3/YOUR_KEY

## Usage
Check current gas status:
   python app.py

Custom RPC:
   python app.py --rpc https://arb1.arbitrum.io/rpc

JSON output:
   python app.py --json

## Example Output
🕒 Timestamp: 2025-11-08T12:45:30.517Z  
🔧 zk-gas-soundness  
🔗 RPC: https://mainnet.infura.io/v3/YOUR_KEY  
🧭 Chain ID: 1 (Ethereum Mainnet)  
🧱 Block: 21051234  
⛽ Base Fee: 8.34 gwei  
💸 Current Gas Price: 9.12 gwei  
📊 Ratio (gas_price/base_fee): 1.09x  
⏱️ Completed in 0.37s  

## Notes
- The ratio helps identify periods of congestion or underpriced gas conditions.  
- If base fee data is unavailable, your RPC may not support EIP-1559 (common on legacy or private networks).  
- Works with Ethereum mainnet and EVM-compatible L2s such as Arbitrum, Base, and Optimism.  
- JSON mode is ideal for automated tracking of network gas health.  
- For zk-rollups and Aztec/Zama research, gas soundness assists in proving consistent fee economics.  
- Exit codes:  
  `0` → success  
  `2` → data fetch error.  
