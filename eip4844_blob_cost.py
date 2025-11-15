#!/usr/bin/env python3
"""
eip4844_blob_cost.py — Estimate ETH cost for zk proof data using EIP-4844 blobs vs calldata.

What it does:
- Fetches latest base fee (EIP-1559) and tries to detect blob base fee.
- Estimates total ETH cost for:
    • Execution gas (--gas-used) with priority tip
    • Data published as blobs (--blobs)
    • Same data as calldata (--calldata-bytes) for comparison
- Allows manual override of blob base fee if the node doesn’t expose it.

Usage examples:
  python eip4844_blob_cost.py --rpc https://mainnet.infura.io/v3/<KEY> --gas-used 1_200_000 --tip-gwei 1.5 --blobs 2
  python eip4844_blob_cost.py --rpc $RPC_URL --calldata-bytes 250_000 --gas-used 800_000 --tip-gwei 2
  python eip4844_blob_cost.py --rpc $RPC_URL --blobs 3 --blob-base-fee-gwei 0.8
"""

import os
import sys
import time
import json
import argparse
from typing import Optional
from web3 import Web3

DEFAULT_RPC = os.getenv("RPC_URL", "https://mainnet.infura.io/v3/your_api_key")
BLOB_SIZE_BYTES = 131072  # 128 KiB per blob (EIP-4844)
CALLDATA_GAS_PER_BYTE = 16  # worst-case (non-zero byte)
# For calldata, you could refine to ~4/16 split for zero/non-zero, but keep conservative here.

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
    return w3

def try_get_blob_base_fee_gwei(w3: Web3) -> Optional[float]:
    """
    Try common places for blob base fee:
      - block['blobBaseFeePerGas'] (some clients)
      - eth_blobBaseFee (non-standard RPC on some providers)
    """
    try:
        latest = w3.eth.get_block("latest")
        v = latest.get("blobBaseFeePerGas", None)
        if v is not None:
            return float(Web3.from_wei(int(v), "gwei"))
    except Exception:
        pass
    # direct RPC (may not exist)
    try:
        resp = w3.provider.make_request("eth_blobBaseFee", [])
        if isinstance(resp, dict) and "result" in resp and resp["result"] is not None:
            return float(Web3.from_wei(int(resp["result"], 16), "gwei"))
    except Exception:
        pass
    return None

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Estimate blob vs calldata costs under current gas conditions.")
    p.add_argument("--rpc", default=DEFAULT_RPC, help="RPC URL (default RPC_URL env)")
    p.add_argument("--gas-used", type=int, default=0, help="Estimated execution gas (excludes data gas)")
    p.add_argument("--tip-gwei", type=float, default=1.0, help="Priority tip in Gwei (default 1.0)")
    p.add_argument("--blobs", type=int, default=0, help="Number of blobs to post (EIP-4844)")
    p.add_argument("--blob-base-fee-gwei", type=float, help="Override blob base fee in Gwei (if node doesn’t expose it)")
    p.add_argument("--calldata-bytes", type=int, default=0, help="Alternative data size as calldata bytes (for compare)")
    p.add_argument("--eth-price", type=float, help="ETH price in USD (optional, for USD cost estimates)")
    p.add_argument("--json", action="store_true", help="Print JSON only")
    return p.parse_args()


def main():
    args = parse_args()
    w3 = connect(args.rpc)
    chain_id = int(w3.eth.chain_id)
    latest = w3.eth.get_block("latest")
    base_fee_gwei = float(Web3.from_wei(int(latest.get("baseFeePerGas", 0)), "gwei"))

    blob_base_fee_gwei = args.blob_base_fee_gwei
    if blob_base_fee_gwei is None:
        blob_base_fee_gwei = try_get_blob_base_fee_gwei(w3)

    # Execution gas cost (EIP-1559): (base + tip) * gas_used
    eff_gwei = base_fee_gwei + args.tip_gwei
    exec_cost_eth = float(Web3.from_wei(Web3.to_wei(eff_gwei, "gwei") * max(args.gas_used, 0), "ether"))

    # Blob data cost: blob_base_fee * blobs * (data gas per blob == 1 unit)
    # In EIP-4844, blob gas is separate; we treat 1 blob gas unit per blob at blobBaseFee.
    blob_cost_eth = None
    if args.blobs > 0 and blob_base_fee_gwei is not None:
        blob_cost_eth = float(Web3.from_wei(Web3.to_wei(blob_base_fee_gwei, "gwei") * args.blobs, "ether"))

    # Calldata cost (conservative): calldata bytes * 16 gas/byte at (base+tip)
    calld_cost_eth = None
    if args.calldata_bytes > 0:
        calldata_gas = args.calldata_bytes * CALLDATA_GAS_PER_BYTE
        calld_cost_eth = float(Web3.from_wei(Web3.to_wei(eff_gwei, "gwei") * calldata_gas, "ether"))
  # Optional USD costs
    exec_cost_usd = blob_cost_usd = calld_cost_usd = None
    if args.eth_price is not None:
        exec_cost_usd = round(exec_cost_eth * args.eth_price, 4)
        if blob_cost_eth is not None:
            blob_cost_usd = round(blob_cost_eth * args.eth_price, 4)
        if calld_cost_eth is not None:
            calld_cost_usd = round(calld_cost_eth * args.eth_price, 4)
       out = {
        "network": network_name(chain_id),
        "chainId": chain_id,
        "blockNumber": int(latest.number),
        "timestampUtc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(latest.timestamp)),
        "baseFeeGwei": round(base_fee_gwei, 4),
        "tipGwei": round(args.tip_gwei, 4),
        "effectivePriceGwei": round(eff_gwei, 4),
        "blobBaseFeeGwei": round(blob_base_fee_gwei, 6) if blob_base_fee_gwei is not None else None,
        "ethPriceUSD": float(args.eth_price) if args.eth_price is not None else None,
        "inputs": {
            "gasUsed": args.gas_used,
            "blobs": args.blobs,
            "calldataBytes": args.calldata_bytes,
        },
        "costsETH": {
            "execution": round(exec_cost_eth, 8),
            "blobs": round(blob_cost_eth, 8) if blob_cost_eth is not None else None,
            "calldata": round(calld_cost_eth, 8) if calld_cost_eth is not None else None,
        },
        "costsUSD": {
            "execution": exec_cost_usd,
            "blobs": blob_cost_usd,
            "calldata": calld_cost_usd,
        },
        "notes": [],
    }

    # Helpful notes
    if args.blobs > 0 and blob_base_fee_gwei is None:
        out["notes"].append("Blob base fee not available from RPC; pass --blob-base-fee-gwei to override.")
    if args.calldata_bytes > 0 and args.blobs > 0:
        # show implied blob count for same data size
        out["notes"].append(f"One blob = {BLOB_SIZE_BYTES} bytes; your calldata size equals ~{(args.calldata_bytes + BLOB_SIZE_BYTES - 1)//BLOB_SIZE_BYTES} blob(s).")
    if args.tip_gwei == 0:
        out["notes"].append("Zero tip may slow confirmation in congestion.")

    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return

    # Pretty print
    print(f"🌐 {out['network']} (chainId {out['chainId']})  🧱 block {out['blockNumber']}  🕒 {out['timestampUtc']} UTC")
    print(f"⛽ Base fee: {out['baseFeeGwei']} Gwei   🎁 Tip: {out['tipGwei']} Gwei   ⚙️ Eff: {out['effectivePriceGwei']} Gwei")
    if out["blobBaseFeeGwei"] is not None:
        print(f"🫧 Blob base fee: {out['blobBaseFeeGwei']} Gwei")
    print(f"📥 Inputs → gasUsed={args.gas_used}  blobs={args.blobs}  calldataBytes={args.calldata_bytes}")
     print("— Estimated Costs (ETH) —")
    exec_line = f"   • Execution       : {out['costsETH']['execution']}"
    blobs_line = f"   • Blobs (data)    : {out['costsETH']['blobs']}" if out["costsETH"]["blobs"] is not None else None
    calld_line = f"   • Calldata (data) : {out['costsETH']['calldata']}" if out["costsETH"]["calldata"] is not None else None

    if args.eth_price is not None:
        if out["costsUSD"]["execution"] is not None:
            exec_line += f"  (~${out['costsUSD']['execution']} USD)"
        if blobs_line is not None and out["costsUSD"]["blobs"] is not None:
            blobs_line += f"  (~${out['costsUSD']['blobs']} USD)"
        if calld_line is not None and out["costsUSD"]["calldata"] is not None:
            calld_line += f"  (~${out['costsUSD']['calldata']} USD)"

    print(exec_line)
    if blobs_line is not None:
        print(blobs_line)
    if calld_line is not None:
        print(calld_line)

    if out["notes"]:
        print("ℹ️  Notes:")
        for n in out["notes"]:
            print(f"   - {n}")

if __name__ == "__main__":
    main()
