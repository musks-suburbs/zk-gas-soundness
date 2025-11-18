# app.py
import os
import sys
import json
import time
import argparse
from datetime import datetime
from web3 import Web3

DEFAULT_RPC = os.environ.get("RPC_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_KEY")

NETWORK_NAMES = {
    1: "Ethereum Mainnet",
    5: "Goerli Testnet",
    11155111: "Sepolia Testnet",
    137: "Polygon Mainnet",
    42161: "Arbitrum One",
    10: "Optimism Mainnet",
    8453: "Base Mainnet",
}

def get_latest_gas_data(w3: Web3) -> dict:
    """
    Fetch latest gas data (base fee, pending gas price, block number).
    """
    try:
        block = w3.eth.get_block("latest")
        base_fee = getattr(block, "baseFeePerGas", None)
        gas_price = w3.eth.gas_price
        return {
            "block_number": block.number,
            "base_fee_wei": base_fee,
            "gas_price_wei": gas_price,
        }
    except Exception as e:
        raise RuntimeError(f"Error fetching gas data: {e}")

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="zk-gas-soundness — monitor gas fee soundness and compare base fees vs current gas price (useful for Aztec/Zama and Web3 analysis)."
    )
    p.add_argument("--rpc", default=DEFAULT_RPC, help="EVM RPC URL (default from RPC_URL)")
    p.add_argument("--timeout", type=int, default=30, help="RPC timeout seconds (default: 30)")
    p.add_argument("--json", action="store_true", help="Output results as JSON")
    return p.parse_args()

def main() -> None:
  start = time.time()
w3 = connect(args.rpc)
print(f"🌐 Connected to {network_name(w3.eth.chain_id)} (chainId {w3.eth.chain_id})")
print(f"🧮 RPC latency: {round(w3.clientVersion and time.time() - start, 3)}s")  # ← add this

    args = parse_args()
print(f"🕒 Execution start time (UTC): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}")

    if not args.rpc.startswith("http"):
        print("❌ Invalid RPC URL format. It must start with 'http' or 'https'.")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": args.timeout}))
    if not w3.is_connected():
        print("❌ RPC connection failed. Check RPC_URL or --rpc.")
        sys.exit(1)

    print(f"🕒 Timestamp: {datetime.utcnow().isoformat()}Z")
    print("🔧 zk-gas-soundness")
    print(f"🔗 RPC: {args.rpc}")

    # Fetch chain ID and network name
    try:
        chain_id = w3.eth.chain_id
        network_name = NETWORK_NAMES.get(chain_id, "Unknown Network")
        print(f"🧭 Chain ID: {chain_id} ({network_name})")
    except Exception:
        print("⚠️ Could not fetch chain ID.")
        chain_id = None
        network_name = "Unknown"

    # Fetch gas data
    try:
        data = get_latest_gas_data(w3)
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(2)

    base_fee = data.get("base_fee_wei")
    gas_price = data.get("gas_price_wei")

    print(f"🧱 Block: {data['block_number']}")
    if base_fee is not None:
        print(f"⛽ Base Fee: {w3.from_wei(base_fee, 'gwei')} gwei")
    print(f"💸 Current Gas Price: {w3.from_wei(gas_price, 'gwei')} gwei")

    # ✅ New: Display approximate gas price in USD for clarity
    try:
        eth_usd = 3000  # Static estimate, can be updated or made dynamic later
        gas_price_usd = (float(w3.from_wei(gas_price, 'gwei')) * 1e-9) * eth_usd
        print(f"💰 Approximate Gas Price: ${gas_price_usd:.8f} per gas unit (at ${eth_usd}/ETH)")
    except Exception:
        print("⚠️ Unable to compute USD equivalent for gas price.")

    # Ratio check
    if base_fee:
        ratio = float(gas_price) / float(base_fee)
        print(f"📊 Ratio (gas_price/base_fee): {ratio:.2f}x")
        if ratio > 2.0:
            print("⚠️ Gas price is unusually high compared to base fee.")
              # New: Warn if gas price is unexpectedly lower than base fee
        if gas_price < base_fee:
            print("⚠️ Gas price is lower than base fee — check RPC accuracy or chain sync.")
            print("⚠️ Gas price is unusually high compared to base fee.")
    else:
        print("⚠️ No base fee data available (legacy chain or RPC).")

    elapsed = time.time() - start
    print(f"⏱️ Completed in {elapsed:.2f}s")

    if args.json:
        output = {
            "rpc": args.rpc,
            "chain_id": chain_id,
            "network_name": network_name,
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            "block_number": data["block_number"],
            "base_fee_wei": base_fee,
            "gas_price_wei": gas_price,
            "ratio_gas_price_to_base_fee": round(float(gas_price) / float(base_fee), 2) if base_fee else None,
            "elapsed_seconds": round(elapsed, 2),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))

    sys.exit(0)

if __name__ == "__main__":
    main()
