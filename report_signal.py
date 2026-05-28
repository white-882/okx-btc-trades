#!/usr/bin/env python3
"""Signal-only report from trader_1m.py — OKX may be unreachable"""
import subprocess, json, sys, os
import pandas as pd, numpy as np
from datetime import datetime, timezone

sys.path.insert(0, '/home/administrator/projects/okx-bot2')
import trader_1m as t

# Run signal detection
signal = t.check_signal()

# Get current BTC price from Gate.io
df = t.fetch_1m_bars(500)

print("═══════════════════════════════════")
print("   V4 1m Adaptive Trader Report")
print("═══════════════════════════════════")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
print()

# Current price
if df is not None and len(df) > 0:
    last = df.iloc[-1]
    print(f"BTC-USDT Spot (Gate.io): ${last['c']:.1f}")
    print(f"  1m Range: {last['l']:.1f} - {last['h']:.1f}")
    print(f"  1m Volume: {last['v']:.2f} BTC")
    print()

# Signal
if signal:
    print(f"SIGNAL: {signal['direction']}")
    print(f"  Entry Price:   ${signal['price']:.1f}")
    print(f"  OB Zone:       ${signal['ob_bottom']:.0f} - ${signal['ob_top']:.0f}")
    print(f"  ATR(14):       {signal['atr']:.1f} ({signal['atr']/signal['price']*100:.2f}%)")
    print(f"  Trend:         {'Bullish' if signal['trend']==1 else 'Bearish'}")
    print(f"  Invalidation:  ${signal['inv']:.0f}" if not np.isnan(signal.get('inv', np.nan)) else "")
    
    # Calculate suggested position
    bal = 10000  # assume
    ep = signal['price']
    atr = signal['atr']
    atr_pct = atr/ep
    pct = t.MAX_POS * min(2.0, t.VOL_TARGET/max(atr_pct, 0.001))
    pct = max(t.MIN_POS, min(t.MAX_POS, pct))
    contracts = max(1, int(bal * pct / (ep * 0.01)))
    actual_pct = contracts * ep * 0.01 / bal
    
    print()
    print(f"Suggested Position (${bal} capital):")
    print(f"  Contracts:     {contracts} ({actual_pct*100:.1f}% of capital)")
    print(f"  Trailing Stop: ${ep - atr * t.ATR_T if signal['direction']=='LONG' else ep + atr * t.ATR_T:.1f} (ATR x {t.ATR_T})")
else:
    print("SIGNAL: None (no valid setup detected)")
    # Check what the indicators show
    if df is not None and len(df) > t.SWING_BASE * 2:
        n = len(df)
        H = df['h'].values; L = df['l'].values; C = df['c'].values
        tr = np.maximum(H-L, np.maximum(abs(H-np.roll(C,1)), abs(L-np.roll(C,1))))
        tr[0] = H[0]-L[0]
        atr = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().values[-1]
        delta = pd.Series(C).diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean().values[-1]
        lss = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean().values[-1]
        rsi = 100 - 100/(1 + gain/(lss+1e-10))
        print(f"  Latest RSI(14): {rsi:.1f}")
        print(f"  Latest ATR(14): {atr:.1f}")

print()
print("Exchange Status:")
print(f"  Gate.io (data):  OK")
print(f"  OKX (trading):   UNREACHABLE — connection reset by firewall")
print(f"  Mode:            Signal analysis only (no execution)")
print("═══════════════════════════════════")
