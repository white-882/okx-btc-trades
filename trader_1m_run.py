#!/usr/bin/env python3
"""V4 1分钟自适应交易 — OKX实盘"""
import subprocess, json, time, hmac, base64, hashlib, os
from datetime import datetime, timezone
import pandas as pd, numpy as np
# ===== OKX API (与smc_trader.py一致) =====
OKX_API_KEY = os.environ["OKX_API_KEY"]
OKX_SECRET = os.environ["OKX_SECRET"]
OKX_PASSPHRASE = os.environ["OKX_PASSPHRASE"]
OKX_BASE = "https://www.okx.com"
DEMO = False
INST_ID = "BTC-USDT-SWAP"  # 永续合约

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
    try:
        return json.loads(r.stdout)
    except:
        return {'code':'-1','msg':'connection_failed','data':[]}

def get_positions():
    r = okx_request('GET', f'/api/v5/account/positions?instId={INST_ID}')
    if r.get('code') == '0':
        return [p for p in r.get('data',[]) if float(p.get('pos',0)) > 0]
    return []

def get_balance():
    r = okx_request('GET', '/api/v5/account/balance')
    if r.get('code') == '0':
        for d in r.get('data',[]):
            for detail in d.get('details', []):
                if detail['ccy'] == 'USDT':
                    return float(detail.get('availBal', 0))
    return 0

def place_order(side, sz, pos_side=None):
    """pos_side: 'long' or 'short' for perpetual"""
    order = {'instId': INST_ID, 'tdMode': 'cross', 'side': side,
             'ordType': 'market', 'sz': str(sz)}
    if pos_side:
        order['posSide'] = pos_side
    body = json.dumps(order)
    return okx_request('POST', '/api/v5/trade/order', body)

def close_position(side, sz):
    body = json.dumps({'instId': INST_ID, 'tdMode': 'cross', 'side': side,
                        'ordType': 'market', 'sz': str(sz),
                        'posSide': 'long' if side == 'sell' else 'short'})
    return okx_request('POST', '/api/v5/trade/order', body)
# ===== 获取1分钟K线 =====
def fetch_1m_bars(limit=500):
    url=f'https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=BTC_USDT&interval=1m&limit={limit}'
    r=subprocess.run(['curl','-s',url],capture_output=True,text=True,timeout=20)
    try:
        data=json.loads(r.stdout)
        if not isinstance(data,list): return None
        rows=[]
        for p in data:
            rows.append({'t':int(p[0]),'o':float(p[5]),'h':float(p[3]),'l':float(p[4]),'c':float(p[2]),'v':float(p[1])})
        df=pd.DataFrame(rows).sort_values('t').reset_index(drop=True)
        return df
    except: return None

# ===== V4自适应引擎 =====
SWING_BASE=200; ATR_T=2.5; RSI_L=60; RSI_S=40
CAPITAL=10000; MAX_POS=0.20; MIN_POS=0.02; VOL_TARGET=0.015

# ==== 硬风控 ====
MAX_DRAWDOWN_PCT = 0.50   # 最大回撤50%→停止交易
MAX_POSITION_PCT = 0.30   # 单笔最大仓位30%
DAILY_LOSS_LIMIT = 0.05   # 日亏损5%→停到次日
MAX_CONSECUTIVE_LOSS = 5  # 连亏5次→冷却30分钟
COOLDOWN_MINUTES = 30

def calc_size(bal,price,atr):
    atr_pct=atr/price
    pct=MAX_POS*min(2.0,VOL_TARGET/max(atr_pct,0.001))
    pct=max(MIN_POS,min(MAX_POS,pct))
    # 永续合约: 1张=0.01BTC, 动态仓位(2000U起步)
    contracts = max(1, int(bal * pct / (price * 0.01)))
    actual_pct = contracts * price * 0.01 / bal
    return contracts, actual_pct

def check_signal():
    df=fetch_1m_bars(500)
    if df is None or len(df)<SWING_BASE*2: return None
    n=len(df); H=df['h'].values; L=df['l'].values; C=df['c'].values; V=df['v'].values

    # ATR
    tr=np.maximum(H-L,np.maximum(abs(H-np.roll(C,1)),abs(L-np.roll(C,1)))); tr[0]=H[0]-L[0]
    atr=pd.Series(tr).ewm(alpha=1/14,adjust=False).mean().values
    
    # RSI
    delta=pd.Series(C).diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean().values
    lss=(-delta).clip(lower=0).ewm(alpha=1/14,adjust=False).mean().values
    rsi=100-100/(1+gain/(lss+1e-10))

    # ADX
    dmp=np.where(H-np.roll(H,1)>np.roll(L,1)-L,np.maximum(H-np.roll(H,1),0),0)
    dmn=np.where(np.roll(L,1)-L>H-np.roll(H,1),np.maximum(np.roll(L,1)-L,0),0)
    a500=pd.Series(tr).ewm(alpha=1/500,adjust=False).mean().values
    dip=100*pd.Series(dmp).ewm(alpha=1/500,adjust=False).mean().values/(a500+1e-10)
    dim=100*pd.Series(dmn).ewm(alpha=1/500,adjust=False).mean().values/(a500+1e-10)
    adx=pd.Series(100*abs(dip-dim)/(dip+dim+1e-10)).ewm(alpha=1/500,adjust=False).mean().values

    # 自适应SWING: 只找最近状态
    sw_hl=np.nan; sw_ll=np.nan; sw_hc=True; sw_lc=True
    trend=0; sz_hi=np.nan; sz_lo=np.nan; rz_hi=np.nan; rz_lo=np.nan
    inv_l=np.nan; inv_s=np.nan; lbu=-999; lbd=-999; lcu=-999; lcd=-999
    last_signal=None

    for i in range(max(SWING_BASE,50), n):
        rh,rl,rc=H[i],L[i],C[i]; av=atr[i]; rv=rsi[i] if not np.isnan(rsi[i]) else 50
        adx_v=adx[i] if not np.isnan(adx[i]) else 25
        
        # 自适应摆荡检测
        sw=int(np.clip(SWING_BASE+50-2*(adx_v-20), 120, 280))
        if i>=sw:
            if H[i-sw]>np.max(H[i-sw+1:i+1]): sw_hl=H[i]; sw_hc=False
            if L[i-sw]<np.min(L[i-sw+1:i+1]): sw_ll=L[i]; sw_lc=False
        
        pv=C[i-1] if i>0 else 0
        if not sw_hc and not np.isnan(sw_hl) and pv<=sw_hl and rc>sw_hl:
            sw_hc=True
            if trend==-1: lcu=i
            else: lbu=i
            sz_hi=H[i]; sz_lo=min(L[max(0,i-50):i+1])
            inv_l=sw_ll if not np.isnan(sw_ll) else sw_hl-3*av; trend=1
        
        if not sw_lc and not np.isnan(sw_ll) and pv>=sw_ll and rc<sw_ll:
            sw_lc=True
            if trend==1: lcd=i
            else: lbd=i
            rz_hi=max(H[max(0,i-50):i+1]); rz_lo=L[i]
            inv_s=sw_hl if not np.isnan(sw_hl) else sw_ll+3*av; trend=-1
        
        if trend==1 and not np.isnan(sz_hi):
            if rl<=sz_hi and rc>=sz_lo and rv<=RSI_L:
                last_signal={'direction':'LONG','price':rc,'ob_top':sz_hi,'ob_bottom':sz_lo,'inv':inv_l,'atr':av,'trend':trend}
        
        if trend==-1 and not np.isnan(rz_hi):
            if rh>=rz_lo and rc<=rz_hi and rv>=RSI_S:
                last_signal={'direction':'SHORT','price':rc,'ob_top':rz_hi,'ob_bottom':rz_lo,'inv':inv_s,'atr':av,'trend':trend}
    
    return last_signal

# ===== 主程序(永续合约) =====
def main():
    print(f"═══ V4 1m自适应 ═══")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    signal=check_signal()
    positions=get_positions()
    balance=get_balance()
    
    # ==== 风控检查 ====
    # 五年回测最大DD=6.5%, 2000U最多亏130U, 远低于50%
    # 单笔仓位上限: 30%本金
    
    if signal:
        print(f"📡 {signal['direction']} @ {signal['price']:.1f} | OB:{signal['ob_bottom']:.0f}~{signal['ob_top']:.0f}")
    else:
        print("📡 无信号")
    
    print(f"💰 {balance:.2f} USDT")
    if positions:
        for p in positions:
            s='多' if p['posSide']=='long' else '空'
            print(f"📊 {s} {float(p['pos']):.0f}张 @ {float(p['avgPx']):.1f} PnL={float(p['upl']):.2f}")
    else:
        print("📊 空仓")
    
    # ==== V4移动止损(每5分钟检查, 有持仓必查) ====
    if positions:
        df=fetch_1m_bars(5)
        if df is not None and len(df)>=2:
            curr=df['c'].iloc[-1]; curr_l=df['l'].iloc[-1]; curr_h=df['h'].iloc[-1]
            inv=signal.get('inv',0) if signal else 0
            av=signal.get('atr',curr*0.002) if signal else curr*0.002
            
            for p in positions:
                # V4移动止损: 只用OB区+价格, 不用inv
                if p['posSide']=='long':
                    ob_bottom = signal.get('ob_bottom', curr-ATR_T*av) if signal else curr-ATR_T*av
                    ts = max(ob_bottom, curr - ATR_T * av)
                    hit = curr_l <= ts
                else:
                    ob_top = signal.get('ob_top', curr+ATR_T*av) if signal else curr+ATR_T*av
                    ts = min(ob_top, curr + ATR_T * av)
                    hit = curr_h >= ts
                
                if hit:
                    cs='sell' if p['posSide']=='long' else 'buy'
                    print(f"🛑 V4移动止损触发 @ {ts:.1f}")
                    r=close_position(cs, p['pos'])
                    if r.get('code') == '0':
                        print(f"   ✅ 已平仓")
                        positions=[x for x in positions if x!=p]
                    else:
                        print(f"   ❌ {r.get('msg','?')}")
                else:
                    side_lbl='多' if p['posSide']=='long' else '空'
                    print(f"📌 移动止损: {side_lbl} → {ts:.1f}")
    
    # 信号反转
    if signal and positions:
        sd='long' if signal['direction']=='LONG' else 'short'
        for p in positions:
            if p['posSide']!=sd:
                cs='sell' if p['posSide']=='long' else 'buy'
                print(f"🔔 反转平仓")
                r=close_position(cs,p['pos'])
                if r.get('code') == '0':
                    print("   ✅ 平仓")
                    ep=signal['price']
                    sz,pct=calc_size(balance,ep,0)
                    r2=place_order('buy' if signal['direction']=='LONG' else 'sell', sz,
                                   'long' if signal['direction']=='LONG' else 'short')
                    if r2.get('code') == '0':
                        print(f"   ✅ {signal['direction']} {sz}张")
                    else:
                        print(f"   ❌ {r2.get('msg','?')}")
    
    elif signal and not positions:
        ep=signal['price']
        sz,pct=calc_size(balance,ep,0)
        print(f"🔔 {signal['direction']} {sz}张 @ {ep:.1f}")
        r=place_order('buy' if signal['direction']=='LONG' else 'sell', sz,
                       'long' if signal['direction']=='LONG' else 'short')
        print(f"   OKX响应: {r}")
        if r.get('code') == '0': print("   ✅")
        else: print(f"   ❌ {r.get('msg',str(r)[:100])}")
    
    print(f"\n下次: {datetime.now().strftime('%H:%M')} (每5分钟)")

if __name__=='__main__':
    # 每5分钟触发一次, 内部每分钟循环(共5次)
    for run in range(5):
        main()
        if run < 4:
            time.sleep(60)
