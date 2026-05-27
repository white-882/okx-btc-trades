#!/usr/bin/env python3
"""
OKX DOM订单簿快照收集 — 每30秒拍一张
GitHub Actions 每5分钟触发，每次跑4.5分钟（约9张快照）
"""
import json, csv, os, time, subprocess
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = 'BTC-USDT-SWAP'
DEPTH = 25  # 25档深度
DATA_DIR = Path('data/dom')
LOOP_SEC = 30
MAX_RUNTIME = 270  # 4.5分钟

def fetch_dom():
    url = f'https://www.okx.com/api/v5/market/books?instId={SYMBOL}&sz={DEPTH}'
    try:
        r = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=15)
        d = json.loads(r.stdout)
        if d.get('code') == '0' and d.get('data'):
            return d['data'][0]
    except: pass
    return None

def dom_to_row(data):
    """Convert DOM data to CSV row: timestamp + bids + asks + stats"""
    ts = int(data['ts'])
    row = [ts]
    
    bids = data['bids']
    asks = data['asks']
    
    # Bid volumes at each level
    bid_vol = 0
    for i in range(min(DEPTH, len(bids))):
        row.append(bids[i][0])  # price
        row.append(bids[i][1])  # size
        row.append(bids[i][3])  # order count
        bid_vol += float(bids[i][1])
    
    # Fill missing levels
    for i in range(len(bids), DEPTH):
        row.extend(['', '', ''])
    
    # Ask volumes
    ask_vol = 0
    for i in range(min(DEPTH, len(asks))):
        row.append(asks[i][0])
        row.append(asks[i][1])
        row.append(asks[i][3])
        ask_vol += float(asks[i][1])
    
    for i in range(len(asks), DEPTH):
        row.extend(['', '', ''])
    
    # Stats
    imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0
    spread = float(asks[0][0]) - float(bids[0][0])
    mid = (float(asks[0][0]) + float(bids[0][0])) / 2
    
    row.extend([round(bid_vol, 2), round(ask_vol, 2), 
                round(imbalance, 4), round(spread, 1), round(mid, 1)])
    
    return row

def header():
    h = ['timestamp_ms']
    for side in ['bid', 'ask']:
        for i in range(DEPTH):
            h.extend([f'{side}{i}_price', f'{side}{i}_size', f'{side}{i}_orders'])
    h.extend(['bid_vol_total', 'ask_vol_total', 'imbalance', 'spread', 'mid_price'])
    return h

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    path = DATA_DIR / f'{today}.csv'
    
    t0 = time.time()
    count = 0
    
    while time.time() - t0 < MAX_RUNTIME:
        data = fetch_dom()
        if data:
            row = dom_to_row(data)
            with open(path, 'a', newline='') as f:
                w = csv.writer(f)
                if not path.exists() or path.stat().st_size == 0:
                    w.writerow(header())
                w.writerow(row)
            count += 1
            
            imb = row[-3]
            print(f"  [{count}] bid_vol={row[-5]} ask_vol={row[-4]} imbalance={imb}")
        else:
            print(f"  [{count+1}] FAIL")
        
        remaining = MAX_RUNTIME - (time.time() - t0)
        if remaining > LOOP_SEC:
            time.sleep(LOOP_SEC)
        else:
            break
    
    print(f"Done: {count} snapshots in {time.time()-t0:.0f}s")

if __name__ == '__main__':
    main()
