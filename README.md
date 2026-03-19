# Public Crypto Toolkit

This repository now contains a single consolidated GUI application:

- `public_crypto_gui.py`

Live page: [mysticalg.github.io/public-crypto-gui](https://mysticalg.github.io/public-crypto-gui/)

## What it does

1. **Address Scanner (public-safe)**
   - Scans only public wallet addresses for BTC / ETH / SOL balances.
   - Rejects secret-like input (private key hex and mnemonic-shaped phrases).
   - Supports bulk scanning and CSV export.

2. **Demo Mnemonics**
   - Generates toy/demo phrases for education/testing only.
   - Not BIP39, not for real funds.

3. **Indicators**
   - Loads OHLCV CSV and computes EMA, MACD, RSI, Bollinger Bands, and Donchian Channels.

## Run

```bash
python public_crypto_gui.py
```

## Requirements

- Python 3.10+
- `requests`

Install dependency:

```bash
pip install requests
```

## Support

If you'd like to support this project, you can buy me a coffee:
[buymeacoffee.com/dhooksterm](https://buymeacoffee.com/dhooksterm)
