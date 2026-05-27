#!/usr/bin/env python3
"""
SMC v4 自动交易机器人 — OKX 模拟账户
每4小时检查信号，自动下单/管理持仓
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
DEMO = True  # 模拟账户

INST_ID = "BTC-USDT-SWAP"  # 永续合约 (也可以用 BTC-USDT 现货)
TRADE_SIZE_USDT = 100      # 每笔 USDT 金额 (模拟小资金)
LEVERAGE = 1               # 杠杆

# ============ 策略参数 (v4 精调) ============
SWING_SIZE = 70
ENTRY_ZONE = 0.2
ATR_TRAIL = 2.5
RSI_LONG_MAX = 60
RSI_SHORT_MIN = 40

# === 15分钟精调参数 ===
ENTRY_DEPTH = 0.33      # 入场深度: LONG=OB区下方33%, SHORT=OB区上方33%
SL_BUFFER = 0.2          # 止损缓冲区: OB边界外0.2%

def okx_request(method, path, body=""):
    """OKX API 签名请求"""
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    sign_str = ts + method.upper() + path + body
    sign = base64.b64encode(hmac.new(OKX_SECRET.encode(), sign_str.encode(), hashlib.sha256).digest()).decode()
    
    headers = {
        'OK-ACCESS-KEY': OKX_API_KEY,
        'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': ts,
        'OK-ACCESS-PASSPHRASE': OKX_PASSPHRASE,
        'Content-Type': 'application/json'
    }
    if DEMO:
        headers['x-simulated-trading'] = '1'
    
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
    """获取当前持仓"""
    r = okx_request('GET', f'/api/v5/account/positions?instId={INST_ID}')
    if r['code'] == '0':
        return [p for p in r['data'] if float(p.get('pos',0)) > 0]
    return []

def get_balance():
    """获取 USDT 余额"""
    r = okx_request('GET', '/api/v5/account/balance')
    if r['code'] == '0':
        for d in r['data']:
            for detail in d.get('details', []):
                if detail['ccy'] == 'USDT':
                    return float(detail.get('availBal', 0))
    return 0

def place_order(side, sz):
    """下单 (市价)"""
    body = json.dumps({
        'instId': INST_ID,
        'tdMode': 'cross',
        'side': side,
        'ordType': 'market',
        'sz': str(sz)
    })
    r = okx_request('POST', '/api/v5/trade/order', body)
    return r

def close_position(side, sz):
    """平仓"""
    body = json.dumps({
        'instId': INST_ID,
        'tdMode': 'cross',
        'side': side,  # 反向: 平多=卖, 平空=买
        'ordType': 'market',
        'sz': str(sz),
        'posSide': 'long' if side == 'sell' else 'short'
    })
    r = okx_request('POST', '/api/v5/trade/order', body)
    return r

def check_signal():
    """获取最新4H信号"""
    # 拉最新4H数据
    try:
        url = 'https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=BTC_USDT&interval=4h&limit=200'
        r = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
    except:
        return None
    
    if not isinstance(data, list) or len(data) < SWING_SIZE*2:
        return None
    
    # Gate.io 格式: [timestamp, volume, close, high, low, open]
    rows = []
    for p in data:
        rows.append({
            'open_time': int(p[0]),
            'open': float(p[5]), 'high': float(p[3]),
            'low': float(p[4]), 'close': float(p[2]),
            'volume': float(p[1])
        })
    df = pd.DataFrame(rows).sort_values('open_time').reset_index(drop=True)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='s')
    
    n = len(df)
    high = df['high'].values; low = df['low'].values; close = df['close'].values
    
    # === 简化的 SMC 信号检测 ===
    def detect_legs(h, l, size):
        leg = np.zeros(n, dtype=int)
        for i in range(size, n):
            if h[i-size] > np.max(h[i-size+1:i+1]): leg[i] = 0
            elif l[i-size] < np.min(l[i-size+1:i+1]): leg[i] = 1
            else: leg[i] = leg[i-1]
        return leg
    
    leg = detect_legs(high, low, SWING_SIZE)
    sw_high = np.diff(leg, prepend=leg[0]) == -1
    sw_low = np.diff(leg, prepend=leg[0]) == 1
    
    # RSI
    delta = pd.Series(close).diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean().values
    loss = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean().values
    rsi_vals = 100 - 100/(1 + gain/(loss+1e-10))
    
    # 状态变量
    sw_hl = sw_ll = np.nan; sw_hc = sw_lc = True
    trend = 0; sz_hi = sz_lo = np.nan; rz_hi = rz_lo = np.nan
    inv_l = inv_s = np.nan
    lbu = lbd = lcu = lcd = -999
    
    last_signal = None
    
    for i in range(SWING_SIZE*2, n):
        rc, rl, rh = close[i], low[i], high[i]
        rsi_v = rsi_vals[i] if not np.isnan(rsi_vals[i]) else 50
        
        if sw_high[i]: sw_hl = high[i]; sw_hc = False
        if sw_low[i]: sw_ll = low[i]; sw_lc = False
        
        pv = close[i-1] if i>0 else 0
        if not sw_hc and not np.isnan(sw_hl) and pv <= sw_hl and rc > sw_hl:
            sw_hc = True
            if trend == -1: lcu = i
            else: lbu = i
            seg = low[max(0, i-100):i+1]
            oi = max(0, i-100) + np.argmin(seg) if len(seg) > 0 else i
            sz_hi = high[min(oi, n-1)]; sz_lo = low[min(oi, n-1)]
            inv_l = sw_ll if not np.isnan(sw_ll) else sw_hl - rc*0.05
            trend = 1
        
        if not sw_lc and not np.isnan(sw_ll) and pv >= sw_ll and rc < sw_ll:
            sw_lc = True
            if trend == 1: lcd = i
            else: lbd = i
            seg = high[max(0, i-100):i+1]
            oi = max(0, i-100) + np.argmax(seg) if len(seg) > 0 else i
            rz_hi = high[min(oi, n-1)]; rz_lo = low[min(oi, n-1)]
            inv_s = sw_hl if not np.isnan(sw_hl) else sw_ll + rc*0.05
            trend = -1
        
        # 信号: 价格进入OB区
        if trend == 1 and not np.isnan(sz_hi):
            fresh = (0 < i-lbu <= 50) or (0 < i-lcu <= 30)
            in_zone = rl <= sz_hi and rc >= sz_lo
            if fresh and in_zone and rsi_v <= RSI_LONG_MAX:
                last_signal = {'direction': 'LONG', 'price': rc, 'time': df['open_time'].iloc[i],
                               'ob_top': sz_hi, 'ob_bottom': sz_lo, 'invalidation': inv_l}
        
        if trend == -1 and not np.isnan(rz_hi):
            fresh = (0 < i-lbd <= 50) or (0 < i-lcd <= 30)
            in_zone = rh >= rz_lo and rc <= rz_hi
            if fresh and in_zone and rsi_v >= RSI_SHORT_MIN:
                last_signal = {'direction': 'SHORT', 'price': rc, 'time': df['open_time'].iloc[i],
                               'ob_top': rz_hi, 'ob_bottom': rz_lo, 'invalidation': inv_s}
    
    # === 核心修改: 当前未完成K线也检查 ===
    # 主循环已经跑了所有历史K线(含当前未完成K线), last_signal 可能是旧信号
    # 现在检查最新一根K(当前进行中的)是否已触碰到OB区
    
    # 如果已有信号且是最近几根K产生的，直接用
    if last_signal and (n - 1 - [i for i in range(n) if df['open_time'].iloc[i] == last_signal['time']][0] <= 3):
        return last_signal
    
    # 否则检查当前K线是否"正在进行中"触碰OB区
    # 判断当前K是否未完成: 4H K线如果open_time距今<4H，就是进行中
    now_ts = int(datetime.now(timezone.utc).timestamp())
    last_open = int(df['open_time'].iloc[-1].timestamp())
    is_current_candle = (now_ts - last_open) < 14400  # 4H = 14400秒
    
    if is_current_candle:
        i = n - 1
        rc, rl, rh = close[i], low[i], high[i]
        rsi_v = rsi_vals[i] if not np.isnan(rsi_vals[i]) else 50
        
        # 用当前已形成的最高/最低判断，不等到收盘
        if trend == 1 and not np.isnan(sz_hi):
            fresh = (0 < i-lbu <= 50) or (0 < i-lcu <= 30)
            # 当前K最低点或当前价碰到OB区就算
            mid_touch = (rl <= sz_hi) or (rc <= sz_hi + (sz_hi - sz_lo) * 0.3)
            if fresh and mid_touch and rsi_v <= RSI_LONG_MAX:
                return {'direction': 'LONG', 'price': rc, 'time': df['open_time'].iloc[i],
                        'ob_top': sz_hi, 'ob_bottom': sz_lo, 'invalidation': inv_l}
        
        if trend == -1 and not np.isnan(rz_hi):
            fresh = (0 < i-lbd <= 50) or (0 < i-lcd <= 30)
            mid_touch = (rh >= rz_lo) or (rc >= rz_lo - (rz_hi - rz_lo) * 0.3)
            if fresh and mid_touch and rsi_v >= RSI_SHORT_MIN:
                return {'direction': 'SHORT', 'price': rc, 'time': df['open_time'].iloc[i],
                        'ob_top': rz_hi, 'ob_bottom': rz_lo, 'invalidation': inv_s}
    
    return last_signal

def fetch_15m_data():
    """拉取15分钟K线(最近96根=24小时)"""
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
    """
    4H信号确认后，在15分钟K线里找最优入场点。
    LONG: 等价格回踩OB区下半部(0~33%) → 入场，止损=OB底-缓冲
    SHORT: 等价格反弹OB区上半部(67~100%) → 入场，止损=OB顶+缓冲
    返回: {'entry': 价格, 'stop': 止损价} 或 None(还没到位)
    """
    df15 = fetch_15m_data()
    if df15 is None:
        return None
    
    direction = signal['direction']
    ob_top = signal['ob_top']
    ob_bottom = signal['ob_bottom']
    ob_range = ob_top - ob_bottom
    
    if ob_range <= 0:
        return None
    
    # 最近15m价格
    current = df15['close'].iloc[-1]
    current_low = df15['low'].iloc[-1]
    current_high = df15['high'].iloc[-1]
    
    # 15m ATR
    high = df15['high'].values; low = df15['low'].values; close = df15['close'].values
    tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close,1)), np.abs(low - np.roll(close,1))))
    tr[0] = high[0] - low[0]
    atr15 = pd.Series(tr).ewm(alpha=2/15, adjust=False).mean().values[-1]
    
    if direction == 'LONG':
        # 入场目标: OB区下33% (ob_bottom + ob_range*0.33)
        target_entry = ob_bottom + ob_range * ENTRY_DEPTH
        # 止损: OB底下方 + ATR缓冲
        stop_loss = ob_bottom - atr15 * 0.5 - ob_range * SL_BUFFER / 100
        
        # 价格是否已经进入目标区?
        in_target_zone = current <= target_entry or current_low <= target_entry
        
        if in_target_zone:
            # 入场: 当前价, 如果更低用最低价
            entry_price = min(current, target_entry)
            return {'entry': entry_price, 'stop': stop_loss, 'atr': atr15}
        else:
            # 还没到目标区，记录等待
            return {'waiting': True, 'target': target_entry, 'current': current, 'stop': stop_loss}
    
    else:  # SHORT
        # 入场目标: OB区上67% (ob_top - ob_range*0.33)
        target_entry = ob_top - ob_range * ENTRY_DEPTH
        # 止损: OB顶上方 + ATR缓冲
        stop_loss = ob_top + atr15 * 0.5 + ob_range * SL_BUFFER / 100
        
        in_target_zone = current >= target_entry or current_high >= target_entry
        
        if in_target_zone:
            entry_price = max(current, target_entry)
            return {'entry': entry_price, 'stop': stop_loss, 'atr': atr15}
        else:
            return {'waiting': True, 'target': target_entry, 'current': current, 'stop': stop_loss}

def main():
    print(f"═══ SMC v4 交易机器人 ═══")
    print(f"账户: OKX {'模拟' if DEMO else '实盘'} | 品种: {INST_ID}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 1. 检查信号
    signal = check_signal()
    if signal:
        print(f"📡 4H信号: {signal['direction']} @ {signal['price']:.1f}")
        print(f"   OB区: {signal['ob_bottom']:.1f} ~ {signal['ob_top']:.1f}")
        
        # 15分钟精调入场
        entry_15m = find_15m_entry(signal)
        if entry_15m:
            if entry_15m.get('waiting'):
                print(f"   ⏳ 等15m入场: 目标{entry_15m['target']:.1f} 当前{entry_15m['current']:.1f} 止损{entry_15m['stop']:.1f}")
            else:
                print(f"   ✅ 15m入场: {entry_15m['entry']:.1f} 止损: {entry_15m['stop']:.1f}")
        else:
            print(f"   ⚠️ 15m数据异常, 用4H信号价入场")
    else:
        print("📡 无4H信号")
    
    # 2. 当前持仓
    positions = get_positions()
    balance = get_balance()
    print(f"💰 余额: {balance:.2f} USDT")
    
    if positions:
        for p in positions:
            pos_side = '多' if p['posSide'] == 'long' else '空'
            print(f"📊 持仓: {pos_side} {float(p['pos']):.4f}张 @ {float(p['avgPx']):.1f} | PnL={float(p['upl']):.2f}")
    else:
        print(f"📊 持仓: 空仓")
    
    # 3. 执行
    if signal and positions:
        sig_dir = 'long' if signal['direction'] == 'LONG' else 'short'
        for p in positions:
            if p['posSide'] != sig_dir:
                close_side = 'sell' if p['posSide'] == 'long' else 'buy'
                print(f"\n🔔 反转: {'多→空' if p['posSide']=='long' else '空→多'}")
                r = close_position(close_side, p['pos'])
                if r['code'] == '0':
                    print(f"   ✅ 已平仓")
                    # 用15m精调入场
                    if entry_15m and not entry_15m.get('waiting'):
                        entry_price = entry_15m['entry']
                        print(f"   🎯 15m精调入: {entry_price:.1f} (止损{entry_15m['stop']:.1f})")
                    else:
                        entry_price = signal['price']
                    sz = round(TRADE_SIZE_USDT / entry_price, 4)
                    r2 = place_order('buy' if signal['direction'] == 'LONG' else 'sell', sz)
                    if r2['code'] == '0':
                        print(f"   ✅ 反向开仓: {signal['direction']} {sz}张 @ {entry_price:.1f}")
                    else:
                        print(f"   ❌ 反向开仓失败: {r2.get('msg','?')}")
                else:
                    print(f"   ❌ 平仓失败: {r.get('msg','?')}")
            else:
                print(f"\n📌 方向一致，持仓不变")
    
    elif signal and not positions:
        # 15m精调入场
        if entry_15m and not entry_15m.get('waiting'):
            entry_price = entry_15m['entry']
            print(f"\n🎯 15m精调入: {entry_price:.1f} (止损{entry_15m['stop']:.1f})")
        elif entry_15m and entry_15m.get('waiting'):
            print(f"\n⏳ 15m还没到位(当前{entry_15m['current']:.1f} 目标{entry_15m['target']:.1f}), 等下次检查")
            entry_price = None
        else:
            entry_price = signal['price']
        
        if entry_price:
            print(f"🔔 开仓: {signal['direction']}")
            sz = round(TRADE_SIZE_USDT / entry_price, 4)
            r = place_order('buy' if signal['direction'] == 'LONG' else 'sell', sz)
            if r['code'] == '0':
                print(f"   ✅ 已下单: {signal['direction']} {sz}张 市价")
            else:
                print(f"   ❌ 下单失败: {r.get('msg','?')}")
    
    elif not signal and positions:
        # 信号消失 → 平仓
        for p in positions:
            side = 'sell' if p['posSide'] == 'long' else 'buy'
            print(f"\n🔔 平仓: {'多' if p['posSide']=='long' else '空'}")
            r = close_position(side, p['pos'])
            if r['code'] == '0':
                print(f"   ✅ 已平仓")
            else:
                print(f"   ❌ 平仓失败: {r.get('msg','?')}")
    
    print(f"\n下一次检查: {datetime.now().strftime('%H:%M')} (cron每小时)")

if __name__ == '__main__':
    main()
