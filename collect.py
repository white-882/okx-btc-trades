#!/usr/bin/env python3
"""OKX trade collector — 循环拉取，模拟1分钟频率"""
import json, csv, os, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = 'BTC-USDT'
DATA_DIR = Path('data')
LOOP_SECONDS = 55  # 每次间隔
MAX_RUNTIME = 270   # 跑4.5分钟（5分钟cron留30秒余量）

def fetch_trades():
    url = f'https://www.okx.com/api/v5/market/history-trades?instId={SYMBOL}&limit=100'
    try:
        r = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=20)
        d = json.loads(r.stdout)
        if d.get('code') == '0':
            return d['data']
    except: pass
    return []

def save_trades(trades, today, existing_ids):
    filepath = DATA_DIR / f'{today}.csv'
    new = 0
    with open(filepath, 'a', newline='') as f:
        w = csv.writer(f)
        if not filepath.exists() or filepath.stat().st_size == 0:
            w.writerow(['timestamp_ms', 'side', 'price', 'size', 'trade_id'])
        for t in trades:
            tid = t['tradeId']
            if tid not in existing_ids:
                w.writerow([t['ts'], t['side'], t['px'], t['sz'], tid])
                existing_ids.add(tid)
                new += 1
    return new

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    # Load existing IDs once
    existing_ids = set()
    filepath = DATA_DIR / f'{today}.csv'
    if filepath.exists():
        with open(filepath) as f:
            for row in csv.reader(f):
                if row and row[0] != 'timestamp_ms':
                    existing_ids.add(row[4])
    
    t0 = time.time()
    total_new = 0
    loop = 0
    
    while time.time() - t0 < MAX_RUNTIME:
        loop += 1
        trades = fetch_trades()
        if trades:
            n = save_trades(trades, today, existing_ids)
            total_new += n
            print(f"  [{loop}] {n} new trades (total: {total_new})")
        else:
            print(f"  [{loop}] 0 trades")
        
        remaining = MAX_RUNTIME - (time.time() - t0)
        if remaining > LOOP_SECONDS:
            time.sleep(LOOP_SECONDS)
        else:
            break
    
    print(f"Done: {total_new} new trades in {loop} loops ({time.time()-t0:.0f}s)")

if __name__ == '__main__':
    main()
