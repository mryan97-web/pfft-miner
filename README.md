# PFFT Miner Bot ⛏️

Automated miner for **Pow Free Fair Token (PFFT)** on Ethereum mainnet.

## Contract

`0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB`

- Max supply: 21,000,000 PFFT
- Per-wallet cap: 10,000 PFFT
- Free mint (0 ETH) — requires Proof-of-Work solve
- PoW difficulty increases as supply grows (24→40 bit)

## Available miners

| Script | Mode | Best for |
|--------|------|----------|
| `pfft_miner.py` | CPU | Any VPS / local machine |
| `pfft_gpu_miner.py` | NVIDIA CUDA GPU | GPU VPS with NVIDIA driver + CUDA |

## How it works

1. Reads current PoW challenge from contract
2. Brute-forces a valid nonce (keccak256 hash must be below difficulty target)
3. Verifies nonce with `isValidPow(wallet, nonce)`
4. Submits `freeMint(powNonce)` transaction (only costs gas)
5. Repeats until wallet cap (10,000 PFFT) or max supply reached

## Setup

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
nano .env   # set PRIVATE_KEY and optional ETH_RPC
```

`.env` example:

```bash
PRIVATE_KEY=your_private_key_here
ETH_RPC=https://ethereum-rpc.publicnode.com
```

## Run CPU miner

```bash
python3 pfft_miner.py
```

CPU-only dependency install if you do not want PyCUDA on non-GPU machine:

```bash
python3 -m pip install web3 pycryptodome
python3 pfft_miner.py
```

## Run NVIDIA GPU miner

Requires:

- NVIDIA GPU VPS
- NVIDIA driver installed
- CUDA toolkit / `nvcc` available
- Python dependency: `pycuda`

Install + run:

```bash
python3 -m pip install -r requirements.txt
python3 pfft_gpu_miner.py
```

Optional GPU tuning:

```bash
GPU_BLOCKS=65535 GPU_THREADS=256 python3 pfft_gpu_miner.py
```

More tuning variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GPU_BLOCKS` | `65535` | CUDA grid blocks per kernel launch |
| `GPU_THREADS` | `256` | CUDA threads per block |
| `GPU_BATCHES_PER_STATUS` | `32` | Kernel batches before status print |
| `PAUSE_BETWEEN_ROUNDS` | `3` | Cooldown seconds after each round |
| `GAS_LIMIT` | `200000` | Gas limit for `freeMint` tx |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PRIVATE_KEY` | required | Mining wallet private key |
| `ETH_RPC` | `https://ethereum-rpc.publicnode.com` | Ethereum RPC endpoint |
| `GAS_LIMIT` | `200000` | Transaction gas limit |
| `PAUSE_BETWEEN_ROUNDS` | `5` CPU / `3` GPU | Cooldown between mints |

## Run as systemd service

CPU service is included:

```bash
sudo cp pfft-miner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pfft-miner

# Check logs
sudo journalctl -u pfft-miner -f
```

For GPU, make a separate service that runs:

```bash
python3 /path/to/pfft_gpu_miner.py
```

## Current stats (May 2026)

| Metric | Value |
|--------|-------|
| Supply | ~6.5M / 21M (31%) |
| Difficulty | 28-bit (7 hex zeros) |
| CPU hashrate | ~175k H/s (Python + pycryptodome) |
| GPU hashrate | Depends on NVIDIA model |
| CPU time per mint | ~25 min at 28-bit |
| PFFT per mint | ~284 |
| Gas per mint | ~0.00002 ETH |

## Security

- `.env` contains your private key — **NEVER commit it**
- `.env` is gitignored
- Use a dedicated mining wallet with only enough ETH for gas
- Do not run with your main wallet private key

## Files

| File | Description |
|------|-------------|
| `pfft_miner.py` | CPU miner script |
| `pfft_gpu_miner.py` | NVIDIA CUDA GPU miner script |
| `requirements.txt` | Python dependencies for CPU + GPU miner |
| `.env.example` | Config template |
| `pfft-miner.service` | CPU systemd unit file |
