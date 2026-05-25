#!/usr/bin/env python3
"""OKX trade collector for GitHub Actions — 每15分钟拉取最新成交"""
import json, csv, os, subprocess
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = 'BTC-USDT'
DATA_DIR = Path('data')

def fetch_trades():
    url = f'https://www.okx.com/api/v5/market/history-trades?instId={SYMBOL}&limit=100'
    try:
        r = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=20)
        d = json.loads(r.stdout)
        if d.get('code') == '0':
            return d['data']
    except: pass
    return []

def main():
    trades = fetch_trades()
    if not trades:
        print("No trades")
        return
    
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filepath = DATA_DIR / f'{today}.csv'
    
    existing_ids = set()
    if filepath.exists():
        with open(filepath) as f:
            for row in csv.reader(f):
                if row and row[0] != 'timestamp_ms':
                    existing_ids.add(row[4])
    
    new_count = 0
    with open(filepath, 'a', newline='') as f:
        w = csv.writer(f)
        if not filepath.exists() or filepath.stat().st_size == 0:
            w.writerow(['timestamp_ms', 'side', 'price', 'size', 'trade_id'])
        for t in trades:
            tid = t['tradeId']
            if tid not in existing_ids:
                w.writerow([t['ts'], t['side'], t['px'], t['sz'], tid])
                existing_ids.add(tid)
                new_count += 1
    
    print(f"Saved {new_count} new trades to {filepath}")

if __name__ == '__main__':
    main()
