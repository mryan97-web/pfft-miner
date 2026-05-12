#!/usr/bin/env python3
"""
PFFT Miner Bot — Pow Free Fair Token
Ethereum Mainnet | Contract: 0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB

Usage:
  cp .env.example .env   # then set PRIVATE_KEY
  python3 pfft_miner.py
"""

import os
import sys
import time
import struct
import signal
from pathlib import Path

# Load .env file if present (no external dependency)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONTRACT = "0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB"
CHAIN_ID = 1
RPC = os.environ.get("ETH_RPC", "https://ethereum-rpc.publicnode.com")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY", "")
GAS_LIMIT = 200000
PAUSE_BETWEEN_ROUNDS = 5

# ---------------------------------------------------------------------------
# Keccak256 (fast, using pycryptodome C extension)
# ---------------------------------------------------------------------------
from Crypto.Hash import keccak as _keccak_mod

def keccak256(data: bytes) -> bytes:
    return _keccak_mod.new(digest_bits=256, data=data).digest()

# ---------------------------------------------------------------------------
# PoW Solver (optimized — pre-compute challenge prefix, pack nonce as bytes)
# ---------------------------------------------------------------------------
def solve_pow(challenge: bytes, target: int, max_hashrate_window: float = 5.0) -> tuple:
    """
    Brute-force PoW. Returns (nonce, hash_bytes) or (None, None).
    """
    nonce = 0
    start = time.time()
    last_report = start
    # Pre-allocate: challenge (32 bytes) + nonce (32 bytes) = 64 bytes
    buf = bytearray(challenge) + bytearray(32)
    challenge_prefix = bytes(buf[:32])

    while True:
        # Pack nonce into last 32 bytes (big-endian)
        struct.pack_into('>QQQQ', buf, 32, 0, 0, 0, nonce)
        h = keccak256(bytes(buf))
        h_int = int.from_bytes(h, 'big')

        if h_int <= target:
            elapsed = time.time() - start
            rate = nonce / elapsed if elapsed > 0 else 0
            print(f"\n  ✅ FOUND nonce={nonce} | {nonce} attempts | {elapsed:.1f}s | {rate:,.0f} H/s")
            return nonce, h

        nonce += 1
        now = time.time()
        if now - last_report >= max_hashrate_window:
            elapsed = now - start
            rate = nonce / elapsed
            remaining = (target.bit_length() and (2**28 / rate)) or 0  # rough ETA
            print(f"  ⛏️  {nonce:,} attempts | {rate:,.0f} H/s | {elapsed:.0f}s elapsed", end='\r')
            last_report = now


# ---------------------------------------------------------------------------
# Contract interaction
# ---------------------------------------------------------------------------
def load_contract(w3):
    ABI = [
        {"inputs":[],"name":"currentPowHexZeros","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[],"name":"totalMinted","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[],"name":"MAX_SUPPLY","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"requested","type":"uint256"}],"name":"calculateActualMint","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"user","type":"address"}],"name":"currentPowChallenge","outputs":[{"type":"bytes32"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"user","type":"address"},{"name":"powNonce","type":"uint256"}],"name":"isValidPow","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"powNonce","type":"uint256"}],"name":"freeMint","outputs":[],"stateMutability":"nonpayable","type":"function"},
        {"inputs":[{"name":"user","type":"address"}],"name":"mintedByAddress","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[],"name":"getInfo","outputs":[{"type":"uint256"},{"type":"uint256"},{"type":"uint256"},{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[],"name":"balanceOf","outputs":[{"type":"uint256"}],"inputs":[{"name":"account","type":"address"}],"stateMutability":"view","type":"function"},
    ]
    # Fix: balanceOf needs proper format
    ABI_CORRECT = []
    for item in ABI:
        fixed = {"type": item["type"], "name": item["name"], "stateMutability": item.get("stateMutability","view")}
        if "inputs" in item:
            fixed["inputs"] = item["inputs"]
        if "outputs" in item:
            fixed["outputs"] = item["outputs"]
        ABI_CORRECT.append(fixed)
    # Add balanceOf properly
    ABI_CORRECT = [x for x in ABI_CORRECT if x["name"] != "balanceOf"]
    ABI_CORRECT.append({
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    })
    return w3.eth.contract(address=w3.to_checksum_address(CONTRACT), abi=ABI_CORRECT)


def get_status(contract, wallet_addr):
    """Get current contract + wallet status."""
    hex_zeros = contract.functions.currentPowHexZeros().call()
    total_minted = contract.functions.totalMinted().call()
    max_supply = contract.functions.MAX_SUPPLY().call()
    next_mint = contract.functions.calculateActualMint(w3.to_wei(1000, 'ether')).call()
    wallet_minted = contract.functions.mintedByAddress(wallet_addr).call()
    wallet_bal = contract.functions.balanceOf(wallet_addr).call()
    target = (2**256 - 1) >> (hex_zeros * 4)
    progress = total_minted * 10000 / max_supply / 100

    return {
        "hex_zeros": hex_zeros,
        "difficulty_bits": hex_zeros * 4,
        "total_minted": total_minted,
        "max_supply": max_supply,
        "next_mint": next_mint,
        "wallet_minted": wallet_minted,
        "wallet_bal": wallet_bal,
        "target": target,
        "progress": progress,
    }


def get_challenge(contract, wallet_addr):
    """Get current PoW challenge for wallet."""
    c = contract.functions.currentPowChallenge(wallet_addr).call()
    return c if isinstance(c, bytes) else c.to_bytes(32, 'big')


def submit_mint(w3, wallet, contract, nonce: int) -> bool:
    """Submit freeMint tx."""
    try:
        fn = contract.functions.freeMint(nonce)
        tx = fn.build_transaction({
            'from': wallet.address,
            'nonce': w3.eth.get_transaction_count(wallet.address),
            'chainId': CHAIN_ID,
            'gas': GAS_LIMIT,
        })
        if 'maxFeePerGas' not in tx and 'maxPriorityFeePerGas' not in tx:
            tx['gasPrice'] = w3.eth.gas_price

        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  📤 TX: https://etherscan.io/tx/0x{tx_hash.hex()}")

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            print(f"  ✅ MINT OK | Block {receipt.blockNumber} | Gas {receipt.gasUsed}")
            return True
        else:
            print(f"  ❌ REVERTED | Gas {receipt.gasUsed}")
            return False
    except Exception as e:
        print(f"  ❌ TX error: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
running = True
def handle_signal(sig, frame):
    global running
    print("\n  ⚠️  Stopping miner...")
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def main():
    from web3 import Web3
    from eth_account import Account

    print("=" * 60)
    print("  ⛏️  PFFT Miner Bot — Pow Free Fair Token")
    print(f"  Contract: {CONTRACT}")
    print(f"  RPC: {RPC}")
    print("=" * 60)

    # Connect
    global w3
    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        print("❌ Cannot connect to RPC")
        sys.exit(1)
    print(f"✅ Connected | Block #{w3.eth.block_number}")

    # Load wallet from PRIVATE_KEY env var
    pk = PRIVATE_KEY.strip()
    if not pk or pk == "your_private_key_here":
        print("❌ PRIVATE_KEY not set!")
        print("   Copy .env.example → .env and set your private key")
        sys.exit(1)
    if not pk.startswith('0x'):
        pk = '0x' + pk
    wallet = Account.from_key(pk)
    print(f"✅ Wallet: {wallet.address}")

    # ETH balance
    eth_bal = w3.eth.get_balance(wallet.address) / 1e18
    print(f"💰 ETH: {eth_bal:.6f}")
    if eth_bal < 0.00005:
        print("⚠️  Low ETH! Need ~0.00005+ ETH for gas")

    # Contract
    contract = load_contract(w3)
    s = get_status(contract, wallet.address)
    print(f"\n📊 Contract:")
    print(f"   Minted: {s['total_minted']/1e18:,.0f} / {s['max_supply']/1e18:,.0f} PFFT ({s['progress']:.1f}%)")
    print(f"   Next mint: ~{s['next_mint']/1e18:,.2f} PFFT")
    print(f"   Difficulty: {s['hex_zeros']} hex zeros ({s['difficulty_bits']}-bit)")
    print(f"   Wallet minted: {s['wallet_minted']/1e18:,.2f} / 10,000 PFFT")
    print(f"   Wallet balance: {s['wallet_bal']/1e18:,.2f} PFFT")

    # Mining loop
    round_num = 0
    total_minted_count = 0
    total_pfft_earned = 0
    global_start = time.time()

    while running:
        round_num += 1
        print(f"\n{'─'*60}")
        print(f"  Round #{round_num}")
        print(f"{'─'*60}")

        # Refresh status
        try:
            s = get_status(contract, wallet.address)
            print(f"  Supply: {s['total_minted']/1e18:,.0f} ({s['progress']:.1f}%) | "
                  f"Next: ~{s['next_mint']/1e18:,.2f} PFFT | "
                  f"Diff: {s['difficulty_bits']}-bit")

            if s['total_minted'] >= s['max_supply']:
                print("  🏁 Max supply reached!")
                break
            if s['wallet_minted'] >= 10_000 * 1e18:
                print("  🏁 Wallet cap (10,000 PFFT) reached!")
                break
        except Exception as e:
            print(f"  ⚠️  Status error: {e}, retrying in 15s...")
            time.sleep(15)
            continue

        # Get challenge
        challenge = get_challenge(contract, wallet.address)

        # Solve PoW
        print(f"  ⛏️  Mining ({s['difficulty_bits']}-bit)...")
        t0 = time.time()
        nonce, h = solve_pow(challenge, s['target'])

        if nonce is None:
            print("  Failed, retrying...")
            continue

        mining_time = time.time() - t0

        # Verify before submitting
        try:
            is_valid = contract.functions.isValidPow(wallet.address, nonce).call()
            if not is_valid:
                print("  ⚠️  Nonce invalid on-chain (supply changed?), re-mining...")
                continue
        except Exception as e:
            print(f"  ⚠️  Verify error: {e}, submitting anyway...")

        # Submit mint
        success = submit_mint(w3, wallet, contract, nonce)
        if success:
            total_minted_count += 1
            earned = s['next_mint'] / 1e18
            total_pfft_earned += earned
            print(f"  💰 +{earned:,.2f} PFFT | Total: {total_pfft_earned:,.2f} PFFT from {total_minted_count} mints")

            # Check new balance
            try:
                bal = contract.functions.balanceOf(wallet.address).call()
                print(f"  💰 PFFT balance: {bal/1e18:,.2f}")
            except:
                pass

        # Summary
        elapsed = time.time() - global_start
        print(f"\n  📈 Session: {total_minted_count} mints | {total_pfft_earned:,.2f} PFFT | {elapsed/60:.1f} min")

        # Pause
        if running:
            print(f"  ⏳ {PAUSE_BETWEEN_ROUNDS}s cooldown...")
            time.sleep(PAUSE_BETWEEN_ROUNDS)

    print(f"\n{'='*60}")
    print(f"  Session Summary")
    print(f"  Mints: {total_minted_count}")
    print(f"  PFFT earned: {total_pfft_earned:,.2f}")
    print(f"  Runtime: {(time.time()-global_start)/60:.1f} min")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
