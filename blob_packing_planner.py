#!/usr/bin/env python3
"""
blob_packing_planner.py — Pack multiple proof payloads into EIP-4844 blobs and estimate costs.

What it does:
- Reads proof sizes (bytes) from CLI or a file (one integer per line).
- Packs payloads into blobs (128 KiB each) using a simple First-Fit-Decreasing heuristic.
- Fetches current base fee and (if available) blob base fee; supports manual override.
- Estimates total ETH cost for:
    • Execution gas (if provided)
    • Blob data (packed) vs. same data as calldata (conservative 16 gas/byte)
- Optional JSON output.

Usage:
  python blob_packing_planner.py --rpc https://mainnet.infura.io/v3/<KEY> --sizes 180000,64000,90000 --tip-gwei 1.5
  python blob_packing_planner.py --file proofsizes.txt --gas-used 1_200_000 --tip-gwei 2 --json
  python blob_packing_planner.py --sizes 250000 --blob-base-fee-gwei 0.8   # override if RPC doesn't expose it
"""

import os
import sys
import time
import json
import math
import argparse
from typing import List, Dict, Any, Optional
from web3 import Web3

__version__ = "0.1.0"
DEFAULT_RPC = os.getenv("RPC_URL", "https://mainnet.infura.io/v3/your_api_key")
DEFAULT_TIP_GWEI = float(os.getenv("BLOB_TIP_GWEI", "1.0"))
BLOB_SIZE_BYTES = 131072        # 128 KiB per blob (EIP-4844)
DATA_GAS_PER_BLOB = 131072      # Blob gas units per blob (per spec)
CALLDATA_GAS_PER_BYTE = 16      # Conservative (non-zero byte)

NETWORKS = {
    1: "Ethereum Mainnet",
    11155111: "Sepolia Testnet",
    10: "Optimism",
    137: "Polygon",
    42161: "Arbitrum One",
    8453: "Base",
    59144: "Linea",
    324: "zkSync Era",
}


def network_name(cid: int) -> str:
    return NETWORKS.get(cid, f"Unknown (chain ID {cid})")

def connect(rpc: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
       if not w3.is_connected():
        print(f"❌ Failed to connect to RPC: {rpc}", file=sys.stderr)
        sys.exit(1)
            # Improve compatibility for PoA / some L2 chains
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    return w3


def try_get_blob_base_fee_gwei(w3: Web3) -> Optional[float]:
    # Try block field first
    try:
        latest = w3.eth.get_block("latest")
        v = latest.get("blobBaseFeePerGas", None)
        if v is not None:
            return float(Web3.from_wei(int(v), "gwei"))
    except Exception:
        pass
    # Non-standard RPC on some providers
    try:
        resp = w3.provider.make_request("eth_blobBaseFee", [])
        if isinstance(resp, dict) and resp.get("result"):
            return float(Web3.from_wei(int(resp["result"], 16), "gwei"))
    except Exception:
        pass
    return None

def parse_sizes_arg(s: str) -> List[int]:
    out: List[int] = []
    for tok in s.split(","):
        tok = tok.strip().replace("_", "")
        if not tok:
            continue
        n = int(tok)
        if n < 0:
            raise ValueError("Sizes must be non-negative")
        out.append(n)
    return out
    avg_utilization = None
    if blob_count > 0:
        used_bytes = total_bytes
        avg_utilization = used_bytes / (blob_count * BLOB_SIZE_BYTES)
def read_sizes_file(path: str) -> List[int]:
    out: List[int] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip().replace("_", "")
                if not line:
                    continue
                n = int(line)
                if n < 0:
                    raise ValueError("Sizes must be non-negative")
                out.append(n)
    except FileNotFoundError:
        print(f"❌ File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"❌ Failed to read file {path}: {e}", file=sys.stderr)
        sys.exit(1)
    return out


def first_fit_decreasing_binpack(sizes: List[int], bin_cap: int) -> List[List[int]]:
    """
    Pack items using the First-Fit Decreasing heuristic.

    Args:
        sizes: List of payload sizes (bytes).
        bin_cap: Capacity of a single blob (bytes).

    Returns:
        A list of bins; each bin is a list of indices into `sizes` that
        fit within a single blob.
    """
    order = sorted(range(len(sizes)), key=lambda i: sizes[i], reverse=True)
    bins: List[List[int]] = []
    remaining: List[int] = []  # remaining capacity per bin
    for i in order:
        placed = False
        for b, rem in enumerate(remaining):
            if sizes[i] <= rem:
                bins[b].append(i)
                remaining[b] -= sizes[i]
                placed = True
                break
        if not placed:
            bins.append([i])
            remaining.append(bin_cap - sizes[i])
    return bins

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Pack proof payloads into blobs and estimate blob vs calldata cost.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--rpc", default=DEFAULT_RPC, help="RPC URL (default from RPC_URL env)")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--sizes", help="Comma-separated payload sizes in bytes (e.g., 180000,64000,90000)")
    grp.add_argument("--file", help="File with one payload size (bytes) per line")
    ap.add_argument("--gas-used", type=int, default=0, help="Estimated execution gas (excludes data gas)")
        ap.add_argument(
        "--tip-gwei",
        type=float,
        default=DEFAULT_TIP_GWEI,
        help="Priority tip (Gwei)",
    )
    ap.add_argument("--blob-base-fee-gwei", type=float, help="Override blob base fee (Gwei)")
    ap.add_argument("--json", action="store_true", help="Print JSON only")
        ap.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program version and exit",
    )
    return ap.parse_args()

def main():
    args = parse_args()
    args.gas_used = max(0, int(args.gas_used))


    if "your_api_key" in args.rpc:
        print(
            "❌ RPC URL appears to still contain the placeholder 'your_api_key'. "
            "Set RPC_URL or pass --rpc with a real endpoint.",
            file=sys.stderr,
        )
        sys.exit(1)


    # Read and validate sizes
    if args.sizes:
        sizes = parse_sizes_arg(args.sizes)
    else:
        sizes = read_sizes_file(args.file)
    sizes = [max(0, s) for s in sizes]
    if any(s > BLOB_SIZE_BYTES for s in sizes):
    raise ValueError(f"Payload exceeds blob capacity ({BLOB_SIZE_BYTES} bytes); split payloads before packing.")

    total_bytes = sum(sizes)
    print(f"📊 Payload size summary: min={min(sizes)} bytes, max={max(sizes)} bytes")


    w3 = connect(args.rpc)
    chain_id = int(w3.eth.chain_id)
    latest = w3.eth.get_block("latest")
    ts_utc = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(latest.timestamp))
    base_fee_gwei = float(Web3.from_wei(int(latest.get("baseFeePerGas", 0)), "gwei"))
from web3.middleware import geth_poa_middleware
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    blob_base_fee_gwei = args.blob_base_fee_gwei
    if blob_base_fee_gwei is None:
        blob_base_fee_gwei = try_get_blob_base_fee_gwei(w3)
if blob_base_fee_gwei is None and (sum(sizes) > 0):
    print("⚠️  Blob base fee not available from RPC; pass --blob-base-fee-gwei to estimate blob cost.")

    # Packing
    bins = first_fit_decreasing_binpack(sizes, BLOB_SIZE_BYTES)
    blob_count = len(bins)
    print(f"🧮 Payload count: {len(sizes)}, Blobs used: {blob_count}")
print(f"📊 Average payload per blob: {round(total_bytes/blob_count if blob_count else 0,2)} bytes/blob")


    # Costs
    eff_gwei = base_fee_gwei + args.tip_gwei
    exec_cost_eth = float(Web3.from_wei(Web3.to_wei(eff_gwei, "gwei") * max(0, args.gas_used), "ether"))

    blob_cost_eth = None
    if blob_base_fee_gwei is not None and blob_count > 0:
        blob_cost_eth = float(Web3.from_wei(Web3.to_wei(blob_base_fee_gwei, "gwei") * blob_count * DATA_GAS_PER_BLOB, "ether"))

    calldata_gas = total_bytes * CALLDATA_GAS_PER_BYTE
    calldata_cost_eth = float(Web3.from_wei(Web3.to_wei(eff_gwei, "gwei") * calldata_gas, "ether"))

    result: Dict[str, Any] = {
        "network": network_name(chain_id),
        "chainId": chain_id,
        "blockNumber": int(latest.number),
        "timestampUtc": ts_utc,
        "baseFeeGwei": round(base_fee_gwei, 4),
        "tipGwei": round(args.tip_gwei, 4),
        "effectiveGwei": round(eff_gwei, 4),
        "blobBaseFeeGwei": round(blob_base_fee_gwei, 6) if blob_base_fee_gwei is not None else None,
        "totals": {
            "payloadBytes": total_bytes,
            "blobCount": blob_count,
        },
        "costsETH": {
            "execution": round(exec_cost_eth, 8),
            "blobs": round(blob_cost_eth, 8) if blob_cost_eth is not None else None,
            "calldata": round(calldata_cost_eth, 8),
        },
            "bins": [
            {
                "blobIndex": i,
                "payloadIndices": bin_,
                "payloadBytes": sum_bytes := sum(sizes[j] for j in bin_),
                "freeBytes": BLOB_SIZE_BYTES - sum_bytes,
            }
            for i, bin_ in enumerate(bins)
                    "totals": {
            "payloadBytes": total_bytes,
            "blobCount": blob_count,
            "totalFreeBytes": total_free_bytes,
            "avgBlobUtilization": round(avg_utilization, 4) if avg_utilization is not None else None,
        },

        ],

        "notes": [],
    }

    if blob_base_fee_gwei is None and blob_count > 0:
        result["notes"].append("Blob base fee not available from RPC; pass --blob-base-fee-gwei to override.")

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    # Pretty print
    print(f"🌐 {result['network']} (chainId {result['chainId']})  🧱 block {result['blockNumber']}  🕒 {result['timestampUtc']} UTC")
    print(f"⛽ Base fee: {result['baseFeeGwei']} Gwei   🎁 Tip: {result['tipGwei']} Gwei   ⚙️ Eff: {result['effectiveGwei']} Gwei")
    if result["blobBaseFeeGwei"] is not None:
        print(f"🫧 Blob base fee: {result['blobBaseFeeGwei']} Gwei")
    print(f"📦 Total payload: {total_bytes} bytes  →  Blobs needed: {blob_count}")
    print("— Estimated Costs (ETH) —")
    print(f"🕒 Calculation performed at: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC")

    print(f"   • Execution       : {result['costsETH']['execution']}")
    if result["costsETH"]["blobs"] is not None:
        print(f"   • Blobs (packed)  : {result['costsETH']['blobs']}")
    print(f"   • Calldata (raw)  : {result['costsETH']['calldata']}")
    if result["costsETH"].get("blobs") is not None and result["costsETH"]["calldata"] > 0:
        ratio = result["costsETH"]["blobs"] / result["costsETH"]["calldata"]
        print(f"📊 Blob-to-calldata cost ratio: {round(ratio, 3)}×")
    if result["bins"]:
        print("— Packing Plan —")
        for b in result["bins"]:
            print(f"   blob#{b['blobIndex']}: payloads={b['payloadIndices']}  bytes={b['payloadBytes']}  free={b['freeBytes']}")
    if result["notes"]:
        print("ℹ️  Notes:")
        for n in result["notes"]:
            print(f"   - {n}")

if __name__ == "__main__":
    main()
