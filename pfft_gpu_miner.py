#!/usr/bin/env python3
"""
PFFT GPU Miner Bot — NVIDIA CUDA version
Ethereum Mainnet | Contract: 0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB

This is a separate GPU script. It does not replace pfft_miner.py.

VPS GPU install notes:
  python3 -m pip install web3 pycuda

Usage:
  cp .env.example .env   # set PRIVATE_KEY and optional ETH_RPC
  python3 pfft_gpu_miner.py

Optional tuning env:
  GPU_BLOCKS=65535
  GPU_THREADS=256
  GPU_BATCHES_PER_STATUS=32
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

# Load .env file if present (no external dependency)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

CONTRACT = "0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB"
CHAIN_ID = 1
RPC = os.environ.get("ETH_RPC", "https://ethereum-rpc.publicnode.com")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY", "")
GAS_LIMIT = int(os.environ.get("GAS_LIMIT", "200000"))
PAUSE_BETWEEN_ROUNDS = int(os.environ.get("PAUSE_BETWEEN_ROUNDS", "3"))

GPU_BLOCKS = int(os.environ.get("GPU_BLOCKS", "65535"))
GPU_THREADS = int(os.environ.get("GPU_THREADS", "256"))
GPU_BATCHES_PER_STATUS = int(os.environ.get("GPU_BATCHES_PER_STATUS", "32"))

running = True
w3 = None


CUDA_SOURCE = r'''
#include <stdint.h>

#define ROL64(a, offset) (((a) << (offset)) ^ ((a) >> (64 - (offset))))

__device__ __constant__ uint64_t RC[24] = {
    0x0000000000000001ULL, 0x0000000000008082ULL,
    0x800000000000808aULL, 0x8000000080008000ULL,
    0x000000000000808bULL, 0x0000000080000001ULL,
    0x8000000080008081ULL, 0x8000000000008009ULL,
    0x000000000000008aULL, 0x0000000000000088ULL,
    0x0000000080008009ULL, 0x000000008000000aULL,
    0x000000008000808bULL, 0x800000000000008bULL,
    0x8000000000008089ULL, 0x8000000000008003ULL,
    0x8000000000008002ULL, 0x8000000000000080ULL,
    0x000000000000800aULL, 0x800000008000000aULL,
    0x8000000080008081ULL, 0x8000000000008080ULL,
    0x0000000080000001ULL, 0x8000000080008008ULL
};

__device__ __forceinline__ uint64_t load64_le(const unsigned char *x) {
    uint64_t r = 0;
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        r |= ((uint64_t)x[i]) << (8 * i);
    }
    return r;
}

__device__ __forceinline__ uint64_t bswap64(uint64_t x) {
    return ((x & 0x00000000000000ffULL) << 56) |
           ((x & 0x000000000000ff00ULL) << 40) |
           ((x & 0x0000000000ff0000ULL) << 24) |
           ((x & 0x00000000ff000000ULL) << 8)  |
           ((x & 0x000000ff00000000ULL) >> 8)  |
           ((x & 0x0000ff0000000000ULL) >> 24) |
           ((x & 0x00ff000000000000ULL) >> 40) |
           ((x & 0xff00000000000000ULL) >> 56);
}

__device__ void keccakf(uint64_t st[25]) {
    const int piln[24] = {
        10, 7, 11, 17, 18, 3, 5, 16,
        8, 21, 24, 4, 15, 23, 19, 13,
        12, 2, 20, 14, 22, 9, 6, 1
    };
    const int rotc[24] = {
        1, 3, 6, 10, 15, 21, 28, 36,
        45, 55, 2, 14, 27, 41, 56, 8,
        25, 43, 62, 18, 39, 61, 20, 44
    };

    for (int round = 0; round < 24; round++) {
        uint64_t bc[5];

        #pragma unroll
        for (int i = 0; i < 5; i++) {
            bc[i] = st[i] ^ st[i + 5] ^ st[i + 10] ^ st[i + 15] ^ st[i + 20];
        }

        #pragma unroll
        for (int i = 0; i < 5; i++) {
            uint64_t t = bc[(i + 4) % 5] ^ ROL64(bc[(i + 1) % 5], 1);
            st[i] ^= t;
            st[i + 5] ^= t;
            st[i + 10] ^= t;
            st[i + 15] ^= t;
            st[i + 20] ^= t;
        }

        uint64_t t = st[1];
        #pragma unroll
        for (int i = 0; i < 24; i++) {
            int j = piln[i];
            uint64_t tmp = st[j];
            st[j] = ROL64(t, rotc[i]);
            t = tmp;
        }

        #pragma unroll
        for (int j = 0; j < 25; j += 5) {
            uint64_t row0 = st[j + 0];
            uint64_t row1 = st[j + 1];
            uint64_t row2 = st[j + 2];
            uint64_t row3 = st[j + 3];
            uint64_t row4 = st[j + 4];
            st[j + 0] = row0 ^ ((~row1) & row2);
            st[j + 1] = row1 ^ ((~row2) & row3);
            st[j + 2] = row2 ^ ((~row3) & row4);
            st[j + 3] = row3 ^ ((~row4) & row0);
            st[j + 4] = row4 ^ ((~row0) & row1);
        }

        st[0] ^= RC[round];
    }
}

__device__ __forceinline__ unsigned char digest_byte(uint64_t st[25], int idx) {
    uint64_t lane = st[idx / 8];
    return (unsigned char)((lane >> (8 * (idx % 8))) & 0xff);
}

__device__ bool digest_le_target(uint64_t st[25], const unsigned char *target) {
    #pragma unroll
    for (int i = 0; i < 32; i++) {
        unsigned char d = digest_byte(st, i);
        unsigned char t = target[i];
        if (d < t) return true;
        if (d > t) return false;
    }
    return true;
}

extern "C" __global__ void mine_kernel(
    const unsigned char *challenge,
    const unsigned char *target,
    unsigned long long start_nonce,
    unsigned long long *nonce_out,
    int *found
) {
    unsigned long long idx = blockIdx.x * blockDim.x + threadIdx.x;
    unsigned long long nonce = start_nonce + idx;

    if (found[0] != 0) return;

    uint64_t st[25];
    #pragma unroll
    for (int i = 0; i < 25; i++) st[i] = 0ULL;

    // Message = challenge(32 bytes) + uint256 nonce(32 bytes, big-endian)
    // Keccak rate is 136 bytes, so this is a single-block message.
    st[0] = load64_le(challenge + 0);
    st[1] = load64_le(challenge + 8);
    st[2] = load64_le(challenge + 16);
    st[3] = load64_le(challenge + 24);
    st[4] = 0ULL;
    st[5] = 0ULL;
    st[6] = 0ULL;
    st[7] = bswap64(nonce);

    // Keccak pad10*1 for 64-byte message: 0x01 at offset 64, 0x80 at offset 135.
    st[8] ^= 0x0000000000000001ULL;
    st[16] ^= 0x8000000000000000ULL;

    keccakf(st);

    if (digest_le_target(st, target)) {
        if (atomicCAS(found, 0, 1) == 0) {
            nonce_out[0] = nonce;
        }
    }
}
'''


ABI = [
    {
        "inputs": [],
        "name": "currentPowHexZeros",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalMinted",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "MAX_SUPPLY",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "requested", "type": "uint256"}],
        "name": "calculateActualMint",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "currentPowChallenge",
        "outputs": [{"type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "powNonce", "type": "uint256"},
        ],
        "name": "isValidPow",
        "outputs": [{"type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "powNonce", "type": "uint256"}],
        "name": "freeMint",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "mintedByAddress",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def handle_signal(sig, frame):
    del sig, frame
    global running
    print("\n  ⚠️  Stopping GPU miner...")
    running = False


def require_gpu():
    try:
        import numpy as np
        import pycuda.autoinit  # noqa: F401
        import pycuda.driver as cuda
        from pycuda.compiler import SourceModule
    except ImportError as exc:
        print("❌ Missing NVIDIA GPU dependency:")
        print("   python3 -m pip install web3 pycuda")
        print(f"   Import error: {exc}")
        sys.exit(1)

    device = cuda.Device(0)
    print(f"✅ CUDA GPU: {device.name()}")
    print(f"   Compute capability: {device.compute_capability()}")

    module = SourceModule(CUDA_SOURCE, no_extern_c=True)
    kernel = module.get_function("mine_kernel")
    return np, cuda, kernel


def load_contract(web3):
    return web3.eth.contract(address=web3.to_checksum_address(CONTRACT), abi=ABI)


def get_status(web3, contract, wallet_addr):
    hex_zeros = contract.functions.currentPowHexZeros().call()
    total_minted = contract.functions.totalMinted().call()
    max_supply = contract.functions.MAX_SUPPLY().call()
    next_mint = contract.functions.calculateActualMint(
        web3.to_wei(1000, "ether")
    ).call()
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
    challenge = contract.functions.currentPowChallenge(wallet_addr).call()
    return challenge if isinstance(challenge, bytes) else challenge.to_bytes(32, "big")


def solve_pow_gpu(np, cuda, kernel, challenge: bytes, target: int):
    challenge_np = np.frombuffer(challenge, dtype=np.uint8).copy()
    target_np = np.frombuffer(target.to_bytes(32, "big"), dtype=np.uint8).copy()
    found_np = np.zeros(1, dtype=np.int32)
    nonce_np = np.zeros(1, dtype=np.uint64)

    challenge_gpu = cuda.mem_alloc(challenge_np.nbytes)
    target_gpu = cuda.mem_alloc(target_np.nbytes)
    found_gpu = cuda.mem_alloc(found_np.nbytes)
    nonce_gpu = cuda.mem_alloc(nonce_np.nbytes)

    cuda.memcpy_htod(challenge_gpu, challenge_np)
    cuda.memcpy_htod(target_gpu, target_np)

    start_nonce = 0
    total_hashes = 0
    start_time = time.time()
    last_report = start_time
    batch_size = GPU_BLOCKS * GPU_THREADS

    while running:
        found_np[0] = 0
        nonce_np[0] = 0
        cuda.memcpy_htod(found_gpu, found_np)
        cuda.memcpy_htod(nonce_gpu, nonce_np)

        for _ in range(GPU_BATCHES_PER_STATUS):
            kernel(
                challenge_gpu,
                target_gpu,
                np.uint64(start_nonce),
                nonce_gpu,
                found_gpu,
                block=(GPU_THREADS, 1, 1),
                grid=(GPU_BLOCKS, 1),
            )
            cuda.Context.synchronize()
            cuda.memcpy_dtoh(found_np, found_gpu)

            total_hashes += batch_size
            if found_np[0]:
                cuda.memcpy_dtoh(nonce_np, nonce_gpu)
                elapsed = time.time() - start_time
                rate = total_hashes / elapsed if elapsed > 0 else 0
                nonce = int(nonce_np[0])
                print(
                    f"\n  ✅ FOUND nonce={nonce} | "
                    f"{total_hashes:,} checked | {rate:,.0f} H/s"
                )
                return nonce

            start_nonce += batch_size

        now = time.time()
        if now - last_report >= 2:
            elapsed = now - start_time
            rate = total_hashes / elapsed if elapsed > 0 else 0
            print(
                f"  ⚡ GPU {rate:,.0f} H/s | "
                f"checked {total_hashes:,} | next nonce {start_nonce:,}",
                end="\r",
            )
            last_report = now

    return None


def submit_mint(web3, wallet, contract, nonce: int) -> bool:
    try:
        fn = contract.functions.freeMint(nonce)
        tx = fn.build_transaction(
            {
                "from": wallet.address,
                "nonce": web3.eth.get_transaction_count(wallet.address),
                "chainId": CHAIN_ID,
                "gas": GAS_LIMIT,
            }
        )
        if "maxFeePerGas" not in tx and "maxPriorityFeePerGas" not in tx:
            tx["gasPrice"] = web3.eth.gas_price

        signed = wallet.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  📤 TX: https://etherscan.io/tx/0x{tx_hash.hex()}")

        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            print(f"  ✅ MINT OK | Block {receipt.blockNumber} | Gas {receipt.gasUsed}")
            return True

        print(f"  ❌ REVERTED | Gas {receipt.gasUsed}")
        return False
    except Exception as exc:
        print(f"  ❌ TX error: {exc}")
        return False


def main():
    from eth_account import Account
    from web3 import Web3

    np, cuda, kernel = require_gpu()

    print("=" * 60)
    print("  🚀 PFFT GPU Miner Bot — NVIDIA CUDA")
    print(f"  Contract: {CONTRACT}")
    print(f"  RPC: {RPC}")
    print(f"  GPU grid: {GPU_BLOCKS} blocks x {GPU_THREADS} threads")
    print("=" * 60)

    global w3
    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        print("❌ Cannot connect to RPC")
        sys.exit(1)
    print(f"✅ Connected | Block #{w3.eth.block_number}")

    private_key = PRIVATE_KEY.strip()
    if not private_key or private_key == "your_private_key_here":
        print("❌ PRIVATE_KEY not set!")
        print("   Copy .env.example → .env and set your private key")
        sys.exit(1)
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    wallet = Account.from_key(private_key)
    print(f"✅ Wallet: {wallet.address}")

    eth_bal = w3.eth.get_balance(wallet.address) / 1e18
    print(f"💰 ETH: {eth_bal:.6f}")
    if eth_bal < 0.00005:
        print("⚠️  Low ETH! Need ~0.00005+ ETH for gas")

    contract = load_contract(w3)
    total_mints = 0
    total_pfft = 0.0
    round_num = 0
    global_start = time.time()

    while running:
        round_num += 1
        print(f"\n{'─' * 60}")
        print(f"  GPU Round #{round_num}")
        print(f"{'─' * 60}")

        try:
            status = get_status(w3, contract, wallet.address)
            print(
                f"  Supply: {status['total_minted'] / 1e18:,.0f} "
                f"({status['progress']:.1f}%) | "
                f"Next: ~{status['next_mint'] / 1e18:,.2f} PFFT | "
                f"Diff: {status['difficulty_bits']}-bit"
            )
            print(
                f"  Wallet minted: {status['wallet_minted'] / 1e18:,.2f} / "
                f"10,000 PFFT | Balance: {status['wallet_bal'] / 1e18:,.2f} PFFT"
            )

            if status["total_minted"] >= status["max_supply"]:
                print("  🏁 Max supply reached!")
                break
            if status["wallet_minted"] >= 10_000 * 1e18:
                print("  🏁 Wallet cap (10,000 PFFT) reached!")
                break
        except Exception as exc:
            print(f"  ⚠️  Status error: {exc}, retrying in 15s...")
            time.sleep(15)
            continue

        challenge = get_challenge(contract, wallet.address)
        print(f"  ⛏️  GPU mining ({status['difficulty_bits']}-bit)...")
        nonce = solve_pow_gpu(np, cuda, kernel, challenge, status["target"])
        if nonce is None:
            print("  Stopped before finding nonce")
            break

        try:
            valid = contract.functions.isValidPow(wallet.address, nonce).call()
            if not valid:
                print("  ⚠️  Nonce invalid on-chain, restarting round...")
                continue
        except Exception as exc:
            print(f"  ⚠️  Verify error: {exc}, submitting anyway...")

        if submit_mint(w3, wallet, contract, nonce):
            total_mints += 1
            earned = status["next_mint"] / 1e18
            total_pfft += earned
            print(
                f"  💰 +{earned:,.2f} PFFT | "
                f"Total: {total_pfft:,.2f} PFFT from {total_mints} mints"
            )

        elapsed = time.time() - global_start
        print(
            f"\n  📈 Session: {total_mints} mints | "
            f"{total_pfft:,.2f} PFFT | {elapsed / 60:.1f} min"
        )
        if running:
            print(f"  ⏳ {PAUSE_BETWEEN_ROUNDS}s cooldown...")
            time.sleep(PAUSE_BETWEEN_ROUNDS)

    print(f"\n{'=' * 60}")
    print("  GPU Session Summary")
    print(f"  Mints: {total_mints}")
    print(f"  PFFT earned: {total_pfft:,.2f}")
    print(f"  Runtime: {(time.time() - global_start) / 60:.1f} min")
    print(f"{'=' * 60}")


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

if __name__ == "__main__":
    main()
