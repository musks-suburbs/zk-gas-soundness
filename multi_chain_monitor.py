#!/usr/bin/env python3
"""
multi_chain_monitor.py

Multi-chain gas fee soundness monitor for zk-gas-soundness.

This script extends the single-RPC CLI in `app.py` by:
- Querying *multiple* RPC endpoints in one run
- Comparing gas_price/base_fee ratios across chains
- Classifying each chain as: healthy / overpriced / underpriced / no_eip1559
- Emitting either a human-readable table or JSON

Usage examples:
    python multi_chain_monitor.py \
        --rpc https://mainnet.infura.io/v3/YOUR_KEY \
        --rpc https://arb1.arbitrum.io/rpc

    python multi_chain_monitor.py \
        --rpc https://mainnet.infura.io/v3/YOUR_KEY \
        --rpc https://base-mainnet.g.alchemy.com/v2/YOUR_KEY \
        --json
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from web3 import Web3


DEFAULT_HIGH_RATIO = 2.0   # > 2x base fee → likely overpriced / congested
DEFAULT_LOW_RATIO = 0.9    # < 0.9x base fee → underpriced vs base fee


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-chain gas fee soundness monitor "
                    "for Ethereum & EVM-compatible (zk) networks."
    )

    parser.add_argument(
        "--rpc",
        action="append",
        dest="rpcs",
        help=(
            "RPC endpoint URL. "
            "Can be passed multiple times to monitor multiple chains. "
            "If omitted, falls back to $RPC_URL if set."
        ),
    )

    parser.add_argument(
        "--name",
        action="append",
        dest="names",
        help=(
            "Optional human-readable name for each RPC (same order as --rpc). "
            "If fewer names than RPCs are provided, remaining names default "
            "to the RPC URL's host."
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of a human-readable table.",
    )

    parser.add_argument(
        "--warn-ratio-high",
        type=float,
        default=DEFAULT_HIGH_RATIO,
        help=f"Threshold for marking a chain as 'overpriced'. Default={DEFAULT_HIGH_RATIO}",
    )

    parser.add_argument(
        "--warn-ratio-low",
        type=float,
        default=DEFAULT_LOW_RATIO,
        help=f"Threshold for marking a chain as 'underpriced'. Default={DEFAULT_LOW_RATIO}",
    )

    return parser.parse_args()


def resolve_rpcs_and_names(args: argparse.Namespace) -> (List[str], List[str]):
    rpcs: List[str] = args.rpcs or []
    names: List[str] = args.names or []

    # Fallback to RPC_URL env if no --rpc was provided
    if not rpcs:
        env_rpc = os.getenv("RPC_URL")
        if not env_rpc:
            print(
                "Error: no --rpc provided and RPC_URL env var is not set.",
                file=sys.stderr,
            )
            sys.exit(2)
        rpcs = [env_rpc]

    # Pad / infer names
    resolved_names: List[str] = []
    for i, rpc in enumerate(rpcs):
        if i < len(names):
            resolved_names.append(names[i])
        else:
            # Try to derive a simple name from hostname
            try:
                host = rpc.split("://", 1)[1]
            except IndexError:
                host = rpc
            resolved_names.append(host)

    return rpcs, resolved_names


def classify_ratio(
    base_fee_gwei: Optional[float],
    gas_price_gwei: Optional[float],
    high: float,
    low: float,
) -> str:
    if base_fee_gwei is None or base_fee_gwei <= 0:
        return "no_eip1559"

    if gas_price_gwei is None:
        return "error"

    ratio = gas_price_gwei / base_fee_gwei

    if ratio > high:
        return "overpriced"
    if ratio < low:
        return "underpriced"
    return "healthy"


def probe_rpc(
    rpc_url: str,
    high: float,
    low: float,
) -> Dict[str, Any]:
    start = time.time()
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 8}))

    result: Dict[str, Any] = {
        "rpc": rpc_url,
        "ok": False,
        "error": None,
        "chain_id": None,
        "block_number": None,
        "base_fee_gwei": None,
        "gas_price_gwei": None,
        "ratio": None,
        "status": None,
        "elapsed_seconds": None,
    }

    try:
        if not w3.is_connected():
            result["error"] = "connection_failed"
            return result

        chain_id = w3.eth.chain_id
        block = w3.eth.get_block("latest")

        # EIP-1559 base fee may be missing on non-1559 chains
        base_fee_wei = getattr(block, "baseFeePerGas", None)
        gas_price_wei = w3.eth.gas_price

        base_fee_gwei = float(base_fee_wei) / 1e9 if base_fee_wei is not None else None
        gas_price_gwei = float(gas_price_wei) / 1e9 if gas_price_wei is not None else None

        ratio = (
            gas_price_gwei / base_fee_gwei
            if base_fee_gwei not in (None, 0)
            and gas_price_gwei is not None
            else None
        )

        status = classify_ratio(base_fee_gwei, gas_price_gwei, high, low)

        result.update(
            {
                "ok": True,
                "chain_id": chain_id,
                "block_number": block.number,
                "base_fee_gwei": base_fee_gwei,
                "gas_price_gwei": gas_price_gwei,
                "ratio": ratio,
                "status": status,
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc) or type(exc).__name__
    finally:
        result["elapsed_seconds"] = round(time.time() - start, 3)

    return result


def format_human_table(
    rows: List[Dict[str, Any]],
    names: List[str],
) -> str:
    headers = [
        "Name",
        "Chain",
        "Block",
        "BaseFee (gwei)",
        "GasPrice (gwei)",
        "Ratio",
        "Status",
        "Time (s)",
    ]

    # Build rows with string representation
    data_rows: List[List[str]] = []
    for name, row in zip(names, rows):
        if not row["ok"]:
            data_rows.append(
                [
                    name,
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    f"ERROR: {row.get('error') or 'unknown'}",
                    f"{row.get('elapsed_seconds', 0):.3f}",
                ]
            )
            continue

        base_fee = (
            f"{row['base_fee_gwei']:.2f}" if row["base_fee_gwei"] is not None else "N/A"
        )
        gas_price = (
            f"{row['gas_price_gwei']:.2f}" if row["gas_price_gwei"] is not None else "N/A"
        )
        ratio = f"{row['ratio']:.2f}x" if row["ratio"] is not None else "N/A"

        data_rows.append(
            [
                name,
                str(row["chain_id"]),
                str(row["block_number"]),
                base_fee,
                gas_price,
                ratio,
                row["status"] or "-",
                f"{row.get('elapsed_seconds', 0):.3f}",
            ]
        )

    # Compute column widths
    all_rows = [headers] + data_rows
    col_widths = [max(len(str(col[i])) for col in all_rows) for i in range(len(headers))]

    def fmt_row(cols: List[str]) -> str:
        return "  ".join(
            str(col).ljust(col_widths[i])
            for i, col in enumerate(cols)
        )

    lines = [fmt_row(headers), fmt_row(["-" * w for w in col_widths])]
    lines.extend(fmt_row(r) for r in data_rows)
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    rpcs, names = resolve_rpcs_and_names(args)

    results: List[Dict[str, Any]] = [
        probe_rpc(rpc, args.warn_ratio_high, args.warn_ratio_low) for rpc in rpcs
    ]

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    if args.json:
        payload = {
            "timestamp": timestamp,
            "multi_chain_gas_soundness": results,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        sys.exit(0 if all(r["ok"] for r in results) else 2)

    # Human-readable mode
    print(f"Timestamp: {timestamp}Z")
    print("zk-gas-soundness :: multi-chain monitor")
    print()
    print(format_human_table(results, names))

    # Exit code: 0 if all good, 2 if any error
    exit_code = 0 if all(r["ok"] for r in results) else 2
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
