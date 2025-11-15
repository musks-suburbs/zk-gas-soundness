#!/usr/bin/env python3
"""
gas_cost_estimator.py — Estimate ETH cost for a contract call given current gas conditions

What it does:
- Connect to RPC, fetch latest block base fee (EIP-1559) and gas price fallback (legacy)
- Accept user inputs: estimated gasUsed, priorityTipGwei or percent-tip
- Compute:
    • expected effectiveGasPrice = baseFee + priorityTip
    • total cost = effectiveGasPrice * gasUsed
    • ETH cost and USD equivalent (optional if price provided)
- Prints a small table and optional JSON output

Usage:
  python gas_cost_estimator.py --rpc https://mainnet.infura.io/v3/<KEY> --gas-used 5_000_000 --tip-gwei 2
  python gas_cost_estimator.py --rpc ... --gas-used 2000000 --tip-percent 0.2 --eth-price 1900
"""

import os
import sys
import time
import json
import argparse
from typing import Optional, Dict
from web3 import Web3

DEFAULT_RPC = os.getenv("RPC_URL", "https://mainnet.infura.io/v3/your_api_key")

NETWORKS = {
    1: "Ethereum Mainnet",
    11155111: "Sepolia Testnet",
    10: "Optimism",
    137: "Polygon",
    42161: "Arbitrum One",
}
def fmt_gwei(v: float, digits: int = 3) -> str:
    return f"{round(v, digits)}"

def network_name(cid: int) -> str:
    return NETWORKS.get(cid, f"Unknown (chain ID {cid})")

def connect(rpc: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        print("❌ Failed to connect to RPC.", file=sys.stderr)
        sys.exit(1)
    return w3

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Estimate ETH cost for a contract call given gasUsed and tip.")
    p.add_argument("--rpc", default=DEFAULT_RPC, help="RPC URL")
    p.add_argument("--gas-used", type=int, required=True, help="Estimated gasUsed for the operation")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--tip-gwei", type=float, help="Priority tip in Gwei")
    group.add_argument("--tip-percent", type=float, help="Priority tip as % of base fee (e.g., 0.1 for 10%)")
    p.add_argument("--eth-price", type=float, help="ETH price in USD (optional)")
    p.add_argument("--json", action="store_true", help="Print JSON output")
    return p.parse_args()

def main():
    args = parse_args()
    w3 = connect(args.rpc)
    chain_id = int(w3.eth.chain_id)
    network = network_name(chain_id)

    latest = w3.eth.get_block("latest")
    base_fee_wei = int(latest.get("baseFeePerGas", 0))
    if base_fee_wei == 0:
        print("⚠️  This network may not support EIP-1559 (no baseFeePerGas).")
    base_fee_gwei = float(Web3.from_wei(base_fee_wei, "gwei"))

    if args.tip_percent is not None:
        tip_gwei = base_fee_gwei * args.tip_percent
    else:
        tip_gwei = args.tip_gwei

    eff_price_gwei = base_fee_gwei + tip_gwei
    gas_used = args.gas_used
    total_wei = Web3.to_wei(eff_price_gwei, "gwei") * gas_used
    total_eth = float(Web3.from_wei(total_wei, "ether"))

    out = {
        "network": network,
        "chainId": chain_id,
        "latestBaseFeeGwei": round(base_fee_gwei, 3),
        "tipGwei": round(tip_gwei, 3),
        "effectivePriceGwei": round(eff_price_gwei, 3),
        "gasUsed": gas_used,
        "estimatedCostETH": round(total_eth, 6),
    }
    if args.eth_price is not None:
        out["estimatedCostUSD"] = round(total_eth * args.eth_price, 2)

    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(f"🌐 {network} (chainId {chain_id})")
              print(f"⛽ Base Fee: {fmt_gwei(base_fee_gwei)} Gwei")
        print(f"🎁 Tip ({tip_mode}): {fmt_gwei(tip_gwei)} Gwei")
        print(f"⚙️  Effective Price: {fmt_gwei(eff_price_gwei)} Gwei")
        print(f"📦 Gas Used: {gas_used}")
        print(f"💰 Estimated cost: {round(total_eth,6)} ETH", end="")
        if args.eth_price is not None:
            print(f"  (~${round(total_eth * args.eth_price,2)} USD)")
        else:
            print()
        print()

if __name__ == "__main__":
    main()
