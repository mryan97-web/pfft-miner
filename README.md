# PFFT Miner Bot ⛏️

Automated miner for **Pow Free Fair Token (PFFT)** on Ethereum mainnet.

## Contract

`0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB`

- Max supply: 21,000,000 PFFT
- Per-wallet cap: 10,000 PFFT
- Free mint (0 ETH) — requires Proof-of-Work solve
- PoW difficulty increases as supply grows (24→40 bit)

## How it works

1. Reads current PoW challenge from contract
2. Brute-forces a valid nonce (keccak256 hash must be below difficulty target)
3. Submits `freeMint(powNonce)` transaction (only costs gas)
4. Repeats until wallet cap (10,000 PFFT) or max supply reached

## Setup

```bash
pip install web3 pycryptodome

# First run auto-generates wallet.json
python3 pfft_miner.py

# Fund wallet with ETH for gas (~0.00005 ETH per mint, ~$0.12)
# Then re-run
python3 pfft_miner.py
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ETH_RPC` | `https://ethereum-rpc.publicnode.com` | Ethereum RPC endpoint |
| `PFFT_WALLET` | `./wallet.json` | Path to wallet JSON |

## Run as systemd service

```bash
sudo cp pfft-miner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pfft-miner

# Check logs
sudo journalctl -u pfft-miner -f
```

## Current stats (May 2026)

| Metric | Value |
|--------|-------|
| Supply | ~6.5M / 21M (31%) |
| Difficulty | 28-bit (7 hex zeros) |
| Hashrate | ~175k H/s (Python) |
| Time per mint | ~25 min |
| PFFT per mint | ~284 |
| Gas per mint | ~0.00002 ETH |

## Security

- `wallet.json` contains your private key — **NEVER commit it**
- Auto-added to `.gitignore`
- `chmod 600` applied on creation
- First run creates a fresh wallet if none exists

## Files

| File | Description |
|------|-------------|
| `pfft_miner.py` | Main miner script |
| `.env.example` | Config template |
| `pfft-miner.service` | Systemd unit file |
| `wallet.json` | Generated wallet (gitignored) |
