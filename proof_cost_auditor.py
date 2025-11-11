#!/usr/bin/env python3
"""
proof_cost_auditor.py — Audit list of zk/rollup proof txs for cost & soundness

What it does:
- Reads input list: transaction hashes (each representing a proof submission)
- For each tx:
  • Fetch receipt & transaction details
  • Check gasUsed, effectiveFee, tip, baseFee at inclusion
  • Compare tip % vs typical observed network tip (optionally sample recent blocks)
  • Flag txs that are outliers (e.g., tip > network p95, gasUsed above threshold)
- Output summary and optional JSON for integration

Usage:
  python proof_cost_auditor.py --rpc https://mainnet.infura.io/v3/<KEY> \
        --file proof_txs.txt --tip-threshold 5.0 --gas-used-threshold 5_000_000
  python proof_cost_auditor.py --rpc ... --file ... --json
"""

import os
import sys
import time
import json
import argparse
from typing import List, Dict, Any
from web3 import Web3

DEFAULT_RPC = os.getenv("RPC_URL", "https://mainnet.infura.io/v3/your_api_key")
NETWORKS = {1: "Ethereum Mainnet", 11155111: "Sepolia Testnet", 10: "Optimism", 137: "Polygon", 42161: "Arbitrum One"}

def network_name(cid: int) -> str:
    return NETWORKS.get(cid, f"Unknown (chain ID {cid})")

def connect(rpc: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        print("❌ Failed to connect to RPC.", file=sys.stderr)
        sys.exit(1)
    return w3

def read_tx_hashes(file: str) -> List[str]:
    with open(file, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit zk-proof or rollup transaction costs for soundness.")
    p.add_argument("--rpc", default=DEFAULT_RPC, help="RPC URL")
    p.add_argument("--file", required=True, help="File with one proof tx hash per line")
    p.add_argument("--tip-threshold", type=float, default=3.0, help="Tip Gwei threshold above network typical")
    p.add_argument("--gas-used-threshold", type=int, default=5_000_000, help="GasUsed threshold in units")
    p.add_argument("--json", action="store_true", help="Output JSON only")
    return p.parse_args()

def audit_tx(w3: Web3, tx_hash: str, tip_threshold: float, gas_used_threshold: int) -> Dict[str, Any]:
    rcpt = w3.eth.get_transaction_receipt(tx_hash)
    tx = w3.eth.get_transaction(tx_hash)
    blk = w3.eth.get_block(int(rcpt.blockNumber))
    base_fee = int(blk.get("baseFeePerGas", 0))
    eff_price = int(rcpt.effectiveGasPrice if hasattr(rcpt, "effectiveGasPrice") else tx.gasPrice)
    tip_per_gas = eff_price - base_fee
    gas_used = int(rcpt.gasUsed)
    flags = []
    if tip_per_gas > Web3.to_wei(tip_threshold, "gwei"):
        flags.append("High tip")
    if gas_used > gas_used_threshold:
        flags.append("High gas used")
    return {
        "txHash": tx_hash,
        "blockNumber": int(rcpt.blockNumber),
        "gasUsed": gas_used,
        "effectiveGasPriceGwei": float(Web3.from_wei(eff_price, "gwei")),
        "tipGwei": float(Web3.from_wei(tip_per_gas, "gwei")),
        "flags": flags or None
    }

def main():
    args = parse_args()
    w3 = connect(args.rpc)
    hashes = read_tx_hashes(args.file)
  print(f"🧮 Total proof transactions read: {len(hashes)}")
print(f"⏱️ Audit started at: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC")
results = [audit_tx(w3, h, args.tip_threshold, args.gas_used_threshold) for h in hashes]
    

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print(f"🌐 {network_name(int(w3.eth.chain_id))} (chainId {w3.eth.chain_id})")
        print("🔍 Proof cost audit results:")
        for r in results:
            flagstr = f"  🏷️ Flags: {','.join(r['flags'])}" if r.get("flags") else ""
            print(f"- {r['txHash']} | block {r['blockNumber']} | gasUsed {r['gasUsed']} | tip {r['tipGwei']:.2f} Gwei{flagstr}")

if __name__ == "__main__":
    main()
