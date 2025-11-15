#!/usr/bin/env python3
"""
gas_outlier_scanner.py — Find gas outlier transactions over recent blocks.

It:
- Scans the last N blocks (sampling every --step blocks for speed).
- Computes per-tx:
    • effectiveGasPrice (Gwei)
    • priority tip (effective - baseFee) in Gwei (legacy fallback supported)
    • gas efficiency (gasUsed / gasLimit * 100)
    • total fee (ETH)
- Flags outliers if they breach thresholds (configurable).
- Prints a concise table, or JSON via --json.

Usage:
  python gas_outlier_scanner.py --rpc https://mainnet.infura.io/v3/<KEY> --blocks 500 --step 2
  python gas_outlier_scanner.py --blocks 300 --tip-gwei-th 5 --eff-low 15 --eff-high 99 --fee-eth-th 0.2 --json
"""

import os
import sys
import time
import json
import argparse
from typing import Any, Dict, List, Optional
from web3 import Web3

DEFAULT_RPC = os.getenv("RPC_URL", "https://mainnet.infura.io/v3/your_api_key")

NETWORKS = {
    1: "Ethereum Mainnet",
    11155111: "Sepolia Testnet",
    10: "Optimism",
    137: "Polygon",
    42161: "Arbitrum One",
}

def network_name(cid: int) -> str:
    return NETWORKS.get(cid, f"Unknown (chain ID {cid})")

def connect(rpc: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        print("❌ Failed to connect to RPC.", file=sys.stderr)
        sys.exit(1)
    # (Optional) better compatibility on some L2/PoA chains:
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    return w3

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scan recent blocks for gas outlier transactions.")
    p.add_argument("--rpc", default=DEFAULT_RPC, help="RPC URL (default from RPC_URL env)")
    p.add_argument("--blocks", type=int, default=300, help="How many recent blocks to scan (default 300)")
    p.add_argument("--step", type=int, default=3, help="Sample every Nth block for speed (default 3)")
    p.add_argument("--tip-gwei-th", type=float, default=5.0, help="Flag if tip >= this Gwei (default 5)")
    p.add_argument("--eff-low", type=float, default=20.0, help="Flag if gas efficiency <= this % (default 20)")
    p.add_argument("--eff-high", type=float, default=99.5, help="Flag if gas efficiency >= this % (default 99.5)")
    p.add_argument("--fee-eth-th", type=float, default=0.1, help="Flag if total fee >= this ETH (default 0.1)")
    p.add_argument("--max-report", type=int, default=100, help="Max outliers to show (default 100)")
    p.add_argument("--json", action="store_true", help="Print JSON instead of text")
    return p.parse_args()

def tx_tip_gwei(tx: Dict[str, Any], base_fee_wei: int, rcpt: Any) -> float:
    # Prefer receipt effectiveGasPrice if available (EIP-1559)
    eff = getattr(rcpt, "effectiveGasPrice", None)
    if eff is None:
        eff = int(tx.get("gasPrice", 0))
    return float(Web3.from_wei(max(0, int(eff) - base_fee_wei), "gwei"))

def scan(w3: Web3, blocks: int, step: int,
         tip_th: float, eff_low: float, eff_high: float, fee_eth_th: float,
         max_report: int) -> Dict[str, Any]:
    head = int(w3.eth.block_number)
    start = max(0, head - blocks + 1)
    outliers: List[Dict[str, Any]] = []
    scanned = 0

    for n in range(head, start - 1, -step):
        blk = w3.eth.get_block(n, full_transactions=True)
        base_fee_wei = int(blk.get("baseFeePerGas", 0))
        ts_utc = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(blk.timestamp))

        # Iterate transactions in block
        for tx in blk.transactions:
            try:
                rcpt = w3.eth.get_transaction_receipt(tx["hash"])
            except Exception:
                continue
            if rcpt is None or rcpt.blockNumber is None:
                continue

            gas_used = int(rcpt.gasUsed)
            gas_limit = int(tx.get("gas", gas_used))
            eff = (gas_used / gas_limit * 100.0) if gas_limit else None

            eff_price_wei = getattr(rcpt, "effectiveGasPrice", None)
            if eff_price_wei is None:
                eff_price_wei = int(tx.get("gasPrice", 0))
            total_fee_eth = float(Web3.from_wei(int(eff_price_wei) * gas_used, "ether"))
            tip_gwei = tx_tip_gwei(tx, base_fee_wei, rcpt)

            # Flag outliers by thresholds
            flags = []
            if tip_gwei >= tip_th:
                flags.append("high_tip")
            if eff is not None and eff <= eff_low:
                flags.append("low_eff")
            if eff is not None and eff >= eff_high:
                flags.append("high_eff")
            if total_fee_eth >= fee_eth_th:
                flags.append("high_total_fee")

            if flags:
                outliers.append({
                    "block": int(blk.number),
                    "timestampUtc": ts_utc,
                    "hash": tx["hash"].hex(),
                    "from": tx.get("from"),
                    "to": tx.get("to"),
                    "gasUsed": gas_used,
                    "gasLimit": gas_limit,
                    "gasEfficiencyPct": round(eff, 2) if eff is not None else None,
                    "baseFeeGwei": float(Web3.from_wei(base_fee_wei, "gwei")),
                    "tipGwei": round(tip_gwei, 3),
                    "effectiveGasPriceGwei": float(Web3.from_wei(int(eff_price_wei), "gwei")),
                    "totalFeeETH": round(total_fee_eth, 6),
                    "flags": flags
                })
                if len(outliers) >= max_report:
                    break
        scanned += 1
        if len(outliers) >= max_report:
            break

    return {
        "network": network_name(int(w3.eth.chain_id)),
        "chainId": int(w3.eth.chain_id),
        "head": head,
        "scannedBlocks": scanned,
        "sampleStep": step,
        "thresholds": {
            "tipGwei": tip_th,
            "effLowPct": eff_low,
            "effHighPct": eff_high,
            "feeEth": fee_eth_th
        },
        "outliers": outliers
    }

def main():
    args = parse_args()
    if args.blocks <= 0 or args.step <= 0:
        print("❌ --blocks and --step must be > 0", file=sys.stderr)
        sys.exit(1)

    w3 = connect(args.rpc)
    t0 = time.time()
    result = scan(
        w3,
        blocks=args.blocks,
        step=args.step,
        tip_th=args.tip_gwei_th,
        eff_low=args.eff_low,
        eff_high=args.eff_high,
        fee_eth_th=args.fee_eth_th,
        max_report=args.max_report
    )
    elapsed = round(time.time() - t0, 2)

    if args.json:
        print(json.dumps({**result, "timingSec": elapsed}, indent=2, sort_keys=True))
        return

    print(f"🌐 {result['network']} (chainId {result['chainId']}) head={result['head']}")
    print(f"📦 Scanned ~{result['scannedBlocks']} blocks (step={result['sampleStep']}) in {elapsed}s")
    th = result["thresholds"]
    print(f"🎯 Thresholds → tip≥{th['tipGwei']} Gwei, eff≤{th['effLowPct']}% | ≥{th['effHighPct']}%, fee≥{th['feeEth']} ETH")
    if not result["outliers"]:
        print("✅ No outliers found under current thresholds.")
        return

    print("\n— Outliers —")
    for r in result["outliers"]:
        fl = ",".join(r["flags"])
        print(f"{r['block']} {r['timestampUtc']}  {r['hash']}")
        print(f"  from {r['from']} → {r['to']}  gas {r['gasUsed']}/{r['gasLimit']} ({r['gasEfficiencyPct']}%)")
        print(f"  base {r['baseFeeGwei']:.3f} G  tip {r['tipGwei']:.3f} G  eff {r['effectiveGasPriceGwei']:.3f} G  fee {r['totalFeeETH']:.6f} ETH  [{fl}]")

if __name__ == "__main__":
    main()
