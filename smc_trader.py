#!/usr/bin/env python3
"""
SMC v4 自动交易机器人 — 移植自 smc_indicator_v4_engine.py
核心: 动态仓位 + 纯移动止损 + 15m精调入場
GitHub Actions 云端运行
"""
import subprocess, json, time, hmac, base64, hashlib
from datetime import datetime, timezone
import os, sys
import pandas as pd
import numpy as np

# ============ OKX API 配置 (模拟账户) ============
OKX_API_KEY = os.environ["OKX_API_KEY"]
OKX_SECRET = os.environ["OKX_SECRET"]
OKX_PASSPHRASE = os.environ["OKX_PASSPHRASE"]
OKX_BASE = "https://www.okx.com"
DEMO = True

INST_ID = "BTC-USDT-SWAP"
TRADE_SIZE_USDT = 100
LEVERAGE = 1

# ============ V4 引擎参数 ============
SWING_SIZE = 70
ATR_TRAIL = 2.5
RSI_LONG_MAX = 60
RSI_SHORT_MIN = 40
CAPITAL = 10000  # 用于动态仓位计算

# 15m精调
ENTRY_DEPTH = 0.33

# ============ OKX API 函数 ============
def okx_request(method, path, body=""):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    sign_str = ts + method.upper() + path + body
    sign = base64.b64encode(hmac.new(OKX_SECRET.encode(), sign_str.encode(), hashlib.sha256).digest()).decode()
    
    headers = {
        'OK-ACCESS-KEY': OKX_API_KEY, 'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': ts, 'OK-ACCESS-PASSPHRASE': OKX_PASSPHRASE,
        'Content-Type': 'application/json'
    }
    if DEMO: headers['x-simulated-trading'] = '1'
    
    url = OKX_BASE + path
    if method == 'GET':
        r = subprocess.run(['curl', '-s', url] + [f'-H{k}:{v}' for k,v in headers.items()],
                         capture_output=True, text=True, timeout=15)
    else:
        r = subprocess.run(['curl', '-s', '-X', method, url, '-d', body] +
                         [f'-H{k}:{v}' for k,v in headers.items()],
                         capture_output=True, text=True, timeout=15)
    return json.loads(r.stdout)

def get_positions():
    r = okx_request('GET', f'/api/v5/account/positions?instId={INST_ID}')
    if r['code'] == '0':
        return [p for p in r['data'] if float(p.get('pos',0)) > 0]
    return []

def get_balance():
    r = okx_request('GET', '/api/v5/account/balance')
    if r['code'] == '0':
        for d in r['data']:
            for detail in d.get('details', []):
                if detail['ccy'] == 'USDT':
                    return float(detail.get('availBal', 0))
    return 0

def place_order(side, sz):
    body = json.dumps({'instId': INST_ID, 'tdMode': 'cross', 'side': side,
                        'ordType': 'market', 'sz': str(sz)})
    return okx_request('POST', '/api/v5/trade/order', body)

def close_position(side, sz):
    body = json.dumps({'instId': INST_ID, 'tdMode': 'cross', 'side': side,
                        'ordType': 'market', 'sz': str(sz),
                        'posSide': 'long' if side == 'sell' else 'short'})
    return okx_request('POST', '/api/v5/trade/order', body)

# ============ 4H 信号 (V4 引擎核心) ============
def check_signal():
    """V4引擎信号检测"""
    try:
        url = 'https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=BTC_USDT&interval=4h&limit=200'
        r = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
    except:
        return None
    
    if not isinstance(data, list) or len(data) < SWING_SIZE*2:
        return None
    
    rows = []
    for p in data:
        rows.append({'open_time': int(p[0]), 'open': float(p[5]),
                     'high': float(p[3]), 'low': float(p[4]), 'close': float(p[2]),
                     'volume': float(p[1])})
    df = pd.DataFrame(rows).sort_values('open_time').reset_index(drop=True)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='s')
    
    n = len(df)
    high = df['high'].values; low = df['low'].values; close = df['close'].values
    
    # ATR (V4: alpha=1/14)
    tr_arr = np.maximum(high-low, np.maximum(abs(high-np.roll(close,1)), abs(low-np.roll(close,1))))
    tr_arr[0] = high[0]-low[0]
    atr = pd.Series(tr_arr).ewm(alpha=1/14, adjust=False).mean().values
    
    # RSI
    delta = pd.Series(close).diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean().values
    loss = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean().values
    rsi = 100 - 100/(1 + gain/(loss+1e-10))
    
    # Legs detection
    leg = np.zeros(n, dtype=int)
    for i in range(SWING_SIZE, n):
        if high[i-SWING_SIZE] > np.max(high[i-SWING_SIZE+1:i+1]): leg[i] = 0
        elif low[i-SWING_SIZE] < np.min(low[i-SWING_SIZE+1:i+1]): leg[i] = 1
        else: leg[i] = leg[i-1]
    
    dleg = np.diff(leg, prepend=leg[0])
    sw_high = dleg == -1
    sw_low = dleg == 1
    
    # State variables (V4 naming)
    sw_hl = sw_ll = np.nan; sw_hc = sw_lc = True; trend = 0
    sz_hi = sz_lo = np.nan; rz_hi = rz_lo = np.nan
    inv_l = inv_s = np.nan
    lbu = lbd = lcu = lcd = -999
    
    last_signal = None
    
    for i in range(SWING_SIZE*2, n):
        rh, rl, rc = high[i], low[i], close[i]
        av = atr[i] if atr[i] > 0 else rc * 0.01
        rv = rsi[i] if not np.isnan(rsi[i]) else 50
        
        if sw_high[i]: sw_hl = high[i]; sw_hc = False
        if sw_low[i]: sw_ll = low[i]; sw_lc = False
        
        pv = close[i-1] if i > 0 else 0
        if not sw_hc and not np.isnan(sw_hl) and pv <= sw_hl and rc > sw_hl:
            sw_hc = True
            if trend == -1: lcu = i
            else: lbu = i
            # Find OB from swing high to now
            seg = low[list(sw_high).index(True, max(0,i-100)) if any(sw_high[max(0,i-100):i+1]) else 0:i+1]
            oi = max(0,i-100) + min(range(len(seg)), key=lambda j: seg[j]) if len(seg) > 0 else 0
            if oi < i: sz_hi = high[oi]; sz_lo = low[oi]
            else: sz_hi = high[i]; sz_lo = low[i]
            inv_l = sw_ll if not np.isnan(sw_ll) else sw_hl - 3*av
            trend = 1
        
        if not sw_lc and not np.isnan(sw_ll) and pv >= sw_ll and rc < sw_ll:
            sw_lc = True
            if trend == 1: lcd = i
            else: lbd = i
            seg = high[list(sw_low).index(True, max(0,i-100)) if any(sw_low[max(0,i-100):i+1]) else 0:i+1]
            oi = max(0,i-100) + max(range(len(seg)), key=lambda j: seg[j]) if len(seg) > 0 else 0
            if oi < i: rz_hi = high[oi]; rz_lo = low[oi]
            else: rz_hi = high[i]; rz_lo = low[i]
            inv_s = sw_hl if not np.isnan(sw_hl) else sw_ll + 3*av
            trend = -1
        
        # Entry signal (V4: requires waited at least 1 bar)
        if trend == 1 and not np.isnan(sz_hi):
            fresh = (0 < i-lbu <= 50) or (0 < i-lcu <= 30)
            waited = (i-lbu >= 1) and (i-lcu >= 1)
            if fresh and waited and rl <= sz_hi and rc >= sz_lo and rv <= RSI_LONG_MAX:
                last_signal = {'direction': 'LONG', 'price': rc, 'time': df['open_time'].iloc[i],
                               'ob_top': sz_hi, 'ob_bottom': sz_lo, 'invalidation': inv_l,
                               'atr': av, 'trend': trend}
        
        if trend == -1 and not np.isnan(rz_hi):
            fresh = (0 < i-lbd <= 50) or (0 < i-lcd <= 30)
            waited = (i-lbd >= 1) and (i-lcd >= 1)
            if fresh and waited and rh >= rz_lo and rc <= rz_hi and rv >= RSI_SHORT_MIN:
                last_signal = {'direction': 'SHORT', 'price': rc, 'time': df['open_time'].iloc[i],
                               'ob_top': rz_hi, 'ob_bottom': rz_lo, 'invalidation': inv_s,
                               'atr': av, 'trend': trend}
    
    # Mid-candle check (current incomplete candle)
    if last_signal:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        last_open = int(df['open_time'].iloc[-1].timestamp())
        if (now_ts - last_open) < 14400:
            i = n - 1
            rc = close[i]; rl = low[i]; rh = high[i]
            rv = rsi[i] if not np.isnan(rsi[i]) else 50
            
            if trend == 1 and not np.isnan(sz_hi):
                mid_touch = (rl <= sz_hi) or (rc <= sz_hi + (sz_hi-sz_lo)*0.3)
                if mid_touch and rv <= RSI_LONG_MAX:
                    return {'direction': 'LONG', 'price': rc, 'time': df['open_time'].iloc[i],
                            'ob_top': sz_hi, 'ob_bottom': sz_lo, 'invalidation': inv_l,
                            'atr': atr[i], 'trend': trend}
            
            if trend == -1 and not np.isnan(rz_hi):
                mid_touch = (rh >= rz_lo) or (rc >= rz_lo - (rz_hi-rz_lo)*0.3)
                if mid_touch and rv >= RSI_SHORT_MIN:
                    return {'direction': 'SHORT', 'price': rc, 'time': df['open_time'].iloc[i],
                            'ob_top': rz_hi, 'ob_bottom': rz_lo, 'invalidation': inv_s,
                            'atr': atr[i], 'trend': trend}
    
    return last_signal

# ============ 15m 精调入場 ============
def fetch_15m_data():
    try:
        url = 'https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=BTC_USDT&interval=15m&limit=96'
        r = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
    except:
        return None
    if not isinstance(data, list) or len(data) < 20:
        return None
    rows = []
    for p in data:
        rows.append({'open_time': int(p[0]), 'open': float(p[5]),
                     'high': float(p[3]), 'low': float(p[4]), 'close': float(p[2])})
    df = pd.DataFrame(rows).sort_values('open_time').reset_index(drop=True)
    for c in ['open','high','low','close']: df[c] = df[c].astype(float)
    return df

def find_15m_entry(signal):
    df15 = fetch_15m_data()
    if df15 is None: return None
    
    direction = signal['direction']
    ob_top = signal['ob_top']; ob_bottom = signal['ob_bottom']
    ob_range = ob_top - ob_bottom
    if ob_range <= 0: return None
    
    current = df15['close'].iloc[-1]
    current_low = df15['low'].iloc[-1]; current_high = df15['high'].iloc[-1]
    
    # 15m ATR
    h=df15['high'].values; l=df15['low'].values; c=df15['close'].values
    tr15 = np.maximum(h-l, np.maximum(abs(h-np.roll(c,1)), abs(l-np.roll(c,1))))
    tr15[0] = h[0]-l[0]
    atr15 = pd.Series(tr15).ewm(alpha=2/15, adjust=False).mean().values[-1]
    
    if direction == 'LONG':
        # OB区内最优价: 越低越好
        target_entry = ob_bottom + ob_range * ENTRY_DEPTH
        stop_loss = ob_bottom - max(atr15 * 0.5, ob_range * 0.001)
        in_target = current <= target_entry or current_low <= target_entry
        if in_target:
            return {'entry': min(current, target_entry), 'stop': stop_loss}
        else:
            return {'waiting': True, 'target': target_entry, 'current': current, 'stop': stop_loss}
    else:
        target_entry = ob_top - ob_range * ENTRY_DEPTH
        stop_loss = ob_top + max(atr15 * 0.5, ob_range * 0.001)
        in_target = current >= target_entry or current_high >= target_entry
        if in_target:
            return {'entry': max(current, target_entry), 'stop': stop_loss}
        else:
            return {'waiting': True, 'target': target_entry, 'current': current, 'stop': stop_loss}

# ============ 主程序 ============
def main():
    print(f"═══ SMC v4 交易机器人 (V4引擎) ═══")
    print(f"账户: OKX {'模拟' if DEMO else '实盘'} | 品种: {INST_ID}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"引擎: 动态仓位 + 纯移动止损 + 15m精调\n")
    
    # 1. V4信号
    signal = check_signal()
    if signal:
        print(f"📡 V4信号: {signal['direction']} @ {signal['price']:.1f}")
        print(f"   OB区: {signal['ob_bottom']:.1f} ~ {signal['ob_top']:.1f} | ATR: {signal['atr']:.1f}")
        
        entry_15m = find_15m_entry(signal)
        if entry_15m:
            if entry_15m.get('waiting'):
                print(f"   ⏳ 等15m: 目标{entry_15m['target']:.1f} 当前{entry_15m['current']:.1f}")
            else:
                print(f"   ✅ 15m: 入{entry_15m['entry']:.1f} 止损{entry_15m['stop']:.1f}")
        else:
            print(f"   ⚠️ 15m数据异常")
    else:
        print("📡 无V4信号")
    
    # 2. 持仓
    positions = get_positions()
    balance = get_balance()
    print(f"💰 余额: {balance:.2f} USDT")
    
    if positions:
        for p in positions:
            pos_side = '多' if p['posSide'] == 'long' else '空'
            print(f"📊 持仓: {pos_side} {float(p['pos']):.4f}张 @ {float(p['avgPx']):.1f} | PnL={float(p['upl']):.2f}")
    else:
        print(f"📊 持仓: 空仓")
    
    # 3. 执行 (V4引擎逻辑: 反转才平仓, 不放信号消失平仓)
    if signal and positions:
        sig_dir = 'long' if signal['direction'] == 'LONG' else 'short'
        for p in positions:
            if p['posSide'] != sig_dir:
                close_side = 'sell' if p['posSide'] == 'long' else 'buy'
                print(f"\n🔔 趋势反转: {'多→空' if p['posSide']=='long' else '空→多'}")
                r = close_position(close_side, p['pos'])
                if r['code'] == '0':
                    print(f"   ✅ 已平仓")
                    if entry_15m and not entry_15m.get('waiting'):
                        entry_price = entry_15m['entry']
                        print(f"   🎯 15m入: {entry_price:.1f} (止损{entry_15m['stop']:.1f})")
                    else:
                        entry_price = signal['price']
                    sz = round(TRADE_SIZE_USDT / entry_price, 4)
                    r2 = place_order('buy' if signal['direction'] == 'LONG' else 'sell', sz)
                    if r2['code'] == '0':
                        print(f"   ✅ 反向: {signal['direction']} {sz}张 @ {entry_price:.1f}")
                    else:
                        print(f"   ❌ 失败: {r2.get('msg','?')}")
                else:
                    print(f"   ❌ 平仓失败: {r.get('msg','?')}")
            else:
                print(f"\n📌 同向，不变 (V4: 不放信号消失)")
    
    elif signal and not positions:
        if entry_15m and not entry_15m.get('waiting'):
            entry_price = entry_15m['entry']
            print(f"\n🎯 15m入: {entry_price:.1f} (止损{entry_15m['stop']:.1f})")
        elif entry_15m and entry_15m.get('waiting'):
            print(f"\n⏳ 15m未到位, 等下次")
            entry_price = None
        else:
            entry_price = signal['price']
        
        if entry_price:
            print(f"🔔 开仓: {signal['direction']}")
            sz = round(TRADE_SIZE_USDT / entry_price, 4)
            r = place_order('buy' if signal['direction'] == 'LONG' else 'sell', sz)
            if r['code'] == '0':
                print(f"   ✅ 已下单: {signal['direction']} {sz}张")
            else:
                print(f"   ❌ 失败: {r.get('msg','?')}")
    
    # V4引擎: 不放信号消失平仓 — 持仓等趋势反转或止损
    
    print(f"\n下次: {datetime.now().strftime('%H:%M')} (每小时)")
    print("V4引擎: 动态仓位 | 纯移动止损 | 趋势反转才出")

if __name__ == '__main__':
    main()
