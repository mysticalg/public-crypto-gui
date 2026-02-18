#!/usr/bin/env python3
"""
Public Crypto Toolkit (GUI)

A consolidated, public-safe app that merges useful ideas from older scripts:
- Public address balance checks (no private key handling)
- Bulk address scanning + CSV export
- Demo mnemonic phrase generation (for testing/education only)
- Basic market indicator calculations from OHLCV CSV (EMA/RSI/MACD/Bollinger/Donchian)

Security policy:
- This app does NOT accept, derive from, or store private keys.
- Inputs that look like private keys are rejected.
"""

from __future__ import annotations

import csv
import json
import random
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable, Optional

try:
    import requests
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: requests. Install with: pip install requests") from exc


APP_TITLE = "Public Crypto Toolkit"
PRIVATE_KEY_HEX_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
BTC_ADDR_RE = re.compile(r"^(bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
SOL_ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

DEMO_WORDS = [
    "apple", "breeze", "cable", "drift", "ember", "forest", "globe", "harbor",
    "ivory", "jungle", "kernel", "ladder", "marble", "nebula", "ocean", "pencil",
    "quantum", "ribbon", "sunset", "thunder", "ultra", "velvet", "whisper", "yellow",
]


@dataclass
class BalanceRow:
    chain: str
    address: str
    balance: float
    tx_count: int | str
    source: str
    note: str = ""


def looks_like_private_key(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    if PRIVATE_KEY_HEX_RE.fullmatch(value):
        return True
    words = value.split()
    if len(words) in {12, 15, 18, 21, 24}:
        return True
    return False


def detect_chain(address: str) -> Optional[str]:
    if BTC_ADDR_RE.fullmatch(address):
        return "BTC"
    if ETH_ADDR_RE.fullmatch(address):
        return "ETH"
    if SOL_ADDR_RE.fullmatch(address):
        return "SOL"
    return None


# ---------------- Balance check adapters ----------------
def get_btc_balance(address: str) -> BalanceRow:
    url = f"https://mempool.space/api/address/{address}"
    res = requests.get(url, timeout=12)
    res.raise_for_status()
    payload = res.json()
    stats = payload.get("chain_stats", {})
    funded = int(stats.get("funded_txo_sum", 0))
    spent = int(stats.get("spent_txo_sum", 0))
    tx_count = int(stats.get("tx_count", 0))
    sat = funded - spent
    return BalanceRow("BTC", address, sat / 1e8, tx_count, "mempool.space")


def get_eth_balance(address: str) -> BalanceRow:
    url = f"https://api.blockchair.com/ethereum/dashboards/address/{address}"
    res = requests.get(url, timeout=15)
    res.raise_for_status()
    payload = res.json()
    addr_data = payload.get("data", {}).get(address, {}).get("address", {})
    wei_balance = int(addr_data.get("balance", 0))
    tx_count = int(addr_data.get("transaction_count", 0))
    return BalanceRow("ETH", address, wei_balance / 1e18, tx_count, "blockchair")


def get_sol_balance(address: str) -> BalanceRow:
    url = "https://api.mainnet-beta.solana.com"
    body = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
    res = requests.post(url, json=body, timeout=12)
    res.raise_for_status()
    payload = res.json()
    lamports = int(payload.get("result", {}).get("value", 0))
    return BalanceRow("SOL", address, lamports / 1e9, "n/a", "solana-rpc")


BALANCE_FETCHERS: dict[str, Callable[[str], BalanceRow]] = {
    "BTC": get_btc_balance,
    "ETH": get_eth_balance,
    "SOL": get_sol_balance,
}


# ---------------- Market indicators ----------------
def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def rsi(values: list[float], period: int = 14) -> list[float]:
    if len(values) < 2:
        return [50.0] * len(values)
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period if len(gains) >= period else (sum(gains) / max(1, len(gains)))
    avg_loss = sum(losses[:period]) / period if len(losses) >= period else (sum(losses) / max(1, len(losses)))

    result = [50.0]
    for i in range(len(gains)):
        if i >= period:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = (avg_gain / avg_loss) if avg_loss else float("inf")
        value = 100 - (100 / (1 + rs)) if rs != float("inf") else 100.0
        result.append(value)
    return result


def bollinger(values: list[float], period: int = 20, mult: float = 2.0) -> tuple[list[float], list[float], list[float]]:
    mids, uppers, lowers = [], [], []
    for i in range(len(values)):
        window = values[max(0, i - period + 1): i + 1]
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / len(window)
        std = var ** 0.5
        mids.append(mean)
        uppers.append(mean + mult * std)
        lowers.append(mean - mult * std)
    return mids, uppers, lowers


def donchian(highs: list[float], lows: list[float], period: int = 20) -> tuple[list[float], list[float]]:
    up, dn = [], []
    for i in range(len(highs)):
        up.append(max(highs[max(0, i - period + 1): i + 1]))
        dn.append(min(lows[max(0, i - period + 1): i + 1]))
    return up, dn


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1120x740")

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True)

        self.balance_tab = ttk.Frame(tabs)
        self.demo_tab = ttk.Frame(tabs)
        self.ind_tab = ttk.Frame(tabs)

        tabs.add(self.balance_tab, text="Address Scanner")
        tabs.add(self.demo_tab, text="Demo Mnemonics")
        tabs.add(self.ind_tab, text="Indicators")

        self._build_balance_tab()
        self._build_demo_tab()
        self._build_indicator_tab()

    # ---------- Address scanner ----------
    def _build_balance_tab(self) -> None:
        frame = self.balance_tab

        ttk.Label(frame, text="Paste public addresses (one per line):").pack(anchor="w", padx=10, pady=(10, 4))
        self.addr_text = tk.Text(frame, height=8)
        self.addr_text.pack(fill="x", padx=10)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="Load File", command=self.load_addresses).pack(side="left")
        ttk.Button(btns, text="Scan", command=self.start_scan).pack(side="left", padx=6)
        ttk.Button(btns, text="Export CSV", command=self.export_csv).pack(side="left")

        cols = ("chain", "address", "balance", "tx_count", "source", "note")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=16)
        for col, w in [("chain", 70), ("address", 400), ("balance", 130), ("tx_count", 90), ("source", 130), ("note", 240)]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var).pack(anchor="w", padx=10, pady=(0, 10))

    def load_addresses(self) -> None:
        path = filedialog.askopenfilename(title="Select text file")
        if not path:
            return
        content = Path(path).read_text(encoding="utf-8", errors="ignore")
        self.addr_text.delete("1.0", "end")
        self.addr_text.insert("1.0", content)

    def _iter_input_addresses(self) -> Iterable[str]:
        raw = self.addr_text.get("1.0", "end")
        for line in raw.splitlines():
            value = line.strip()
            if value:
                yield value

    def start_scan(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        addresses = list(self._iter_input_addresses())
        if not addresses:
            messagebox.showinfo(APP_TITLE, "Please add at least one address.")
            return

        def worker() -> None:
            rows: list[BalanceRow] = []
            blocked = 0
            for addr in addresses:
                if looks_like_private_key(addr):
                    blocked += 1
                    rows.append(BalanceRow("-", addr[:20] + "…", 0.0, "-", "local", "blocked: secret-like input"))
                    continue

                chain = detect_chain(addr)
                if not chain:
                    rows.append(BalanceRow("-", addr, 0.0, "-", "local", "unrecognized address format"))
                    continue

                try:
                    row = BALANCE_FETCHERS[chain](addr)
                except Exception as exc:
                    row = BalanceRow(chain, addr, 0.0, "-", "remote", f"error: {exc}")
                rows.append(row)

            self.after(0, lambda: self._scan_done(rows, blocked))

        self.status_var.set("Scanning...")
        threading.Thread(target=worker, daemon=True).start()

    def _scan_done(self, rows: list[BalanceRow], blocked: int) -> None:
        for row in rows:
            self.tree.insert("", "end", values=(
                row.chain,
                row.address,
                f"{row.balance:.10f}",
                row.tx_count,
                row.source,
                row.note,
            ))
        self.status_var.set(f"Done: {len(rows)} rows ({blocked} blocked secret-like inputs).")

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["chain", "address", "balance", "tx_count", "source", "note"])
            for iid in self.tree.get_children():
                writer.writerow(self.tree.item(iid, "values"))
        messagebox.showinfo(APP_TITLE, f"Exported to {path}")

    # ---------- Demo mnemonics ----------
    def _build_demo_tab(self) -> None:
        frame = self.demo_tab
        info = (
            "Educational only: generates random demo phrases from a toy word list.\n"
            "These are NOT BIP39 wallet seeds and cannot recover funds."
        )
        ttk.Label(frame, text=info).pack(anchor="w", padx=10, pady=(10, 6))

        controls = ttk.Frame(frame)
        controls.pack(anchor="w", padx=10)
        self.demo_count = tk.IntVar(value=10)
        ttk.Label(controls, text="Count:").pack(side="left")
        ttk.Spinbox(controls, from_=1, to=500, width=8, textvariable=self.demo_count).pack(side="left", padx=(5, 10))
        ttk.Button(controls, text="Generate", command=self.generate_demo).pack(side="left")

        self.demo_text = tk.Text(frame)
        self.demo_text.pack(fill="both", expand=True, padx=10, pady=10)

    def generate_demo(self) -> None:
        count = max(1, min(int(self.demo_count.get()), 500))
        lines = []
        for _ in range(count):
            words = random.sample(DEMO_WORDS, 12)
            lines.append(" ".join(words))
        self.demo_text.delete("1.0", "end")
        self.demo_text.insert("1.0", "\n".join(lines))

    # ---------- Indicators ----------
    def _build_indicator_tab(self) -> None:
        frame = self.ind_tab
        ttk.Label(frame, text="Load OHLCV CSV with columns: timestamp,open,high,low,close,volume").pack(anchor="w", padx=10, pady=(10, 6))

        controls = ttk.Frame(frame)
        controls.pack(anchor="w", padx=10)
        ttk.Button(controls, text="Open CSV", command=self.load_ohlcv).pack(side="left")
        ttk.Button(controls, text="Compute", command=self.compute_indicators).pack(side="left", padx=8)

        self.ind_text = tk.Text(frame)
        self.ind_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.ohlcv_rows: list[dict[str, str]] = []

    def load_ohlcv(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All files", "*")])
        if not path:
            return
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            self.ohlcv_rows = list(csv.DictReader(f))
        self.ind_text.delete("1.0", "end")
        self.ind_text.insert("1.0", f"Loaded {len(self.ohlcv_rows)} rows from {path}\n")

    def compute_indicators(self) -> None:
        if not self.ohlcv_rows:
            messagebox.showinfo(APP_TITLE, "Load an OHLCV CSV first.")
            return

        try:
            closes = [float(r["close"]) for r in self.ohlcv_rows]
            highs = [float(r["high"]) for r in self.ohlcv_rows]
            lows = [float(r["low"]) for r in self.ohlcv_rows]
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Invalid CSV format: {exc}")
            return

        ema_fast = ema(closes, 12)
        ema_slow = ema(closes, 26)
        macd_line = [a - b for a, b in zip(ema_fast, ema_slow)]
        macd_signal = ema(macd_line, 9)
        rsi_vals = rsi(closes, 14)
        mid, up, dn = bollinger(closes, 20, 2.0)
        don_up, don_dn = donchian(highs, lows, 20)

        idx = len(closes) - 1
        summary = {
            "timestamp": self.ohlcv_rows[idx].get("timestamp", "n/a"),
            "close": closes[idx],
            "ema12": ema_fast[idx],
            "ema26": ema_slow[idx],
            "macd": macd_line[idx],
            "macd_signal": macd_signal[idx],
            "rsi14": rsi_vals[idx],
            "bb_mid": mid[idx],
            "bb_upper": up[idx],
            "bb_lower": dn[idx],
            "donchian_upper": don_up[idx],
            "donchian_lower": don_dn[idx],
            "computed_at": datetime.utcnow().isoformat() + "Z",
        }

        self.ind_text.delete("1.0", "end")
        self.ind_text.insert("1.0", json.dumps(summary, indent=2))


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
