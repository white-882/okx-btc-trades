#!/usr/bin/env python3
"""V4 1m signal check - Gate.io only, no OKX dependency"""
import subprocess, json, time
from datetime import datetime
import pandas as pd, numpy as np

SWING_BASE=200; ATR_T=2.5; RSI_L=60; RSI_S=40
CAPITAL=10000; MAX_POS=0.20; MIN_POS=0.02; VOL_TARGET=0.015

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

def check_signal():
    df=fetch_1m_bars(500)
    if df is None or len(df)<SWING_BASE*2: return None
    n=len(df); H=df['h'].values; L=df['l'].values; C=df['c'].values; V=df['v'].values

    tr=np.maximum(H-L,np.maximum(abs(H-np.roll(C,1)),abs(L-np.roll(C,1)))); tr[0]=H[0]-L[0]
    atr=pd.Series(tr).ewm(alpha=1/14,adjust=False).mean().values

    delta=pd.Series(C).diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean().values
    lss=(-delta).clip(lower=0).ewm(alpha=1/14,adjust=False).mean().values
    rsi=100-100/(1+gain/(lss+1e-10))

    dmp=np.where(H-np.roll(H,1)>np.roll(L,1)-L,np.maximum(H-np.roll(H,1),0),0)
    dmn=np.where(np.roll(L,1)-L>H-np.roll(H,1),np.maximum(np.roll(L,1)-L,0),0)
    a500=pd.Series(tr).ewm(alpha=1/500,adjust=False).mean().values
    dip=100*pd.Series(dmp).ewm(alpha=1/500,adjust=False).mean().values/(a500+1e-10)
    dim=100*pd.Series(dmn).ewm(alpha=1/500,adjust=False).mean().values/(a500+1e-10)
    adx=pd.Series(100*abs(dip-dim)/(dip+dim+1e-10)).ewm(alpha=1/500,adjust=False).mean().values

    sw_hl=np.nan; sw_ll=np.nan; sw_hc=True; sw_lc=True
    trend=0; sz_hi=np.nan; sz_lo=np.nan; rz_hi=np.nan; rz_lo=np.nan
    inv_l=np.nan; inv_s=np.nan
    last_signal=None

    for i in range(max(SWING_BASE,50), n):
        rh,rl,rc=H[i],L[i],C[i]; av=atr[i]; rv=rsi[i] if not np.isnan(rsi[i]) else 50
        adx_v=adx[i] if not np.isnan(adx[i]) else 25
        
        sw=int(np.clip(SWING_BASE+50-2*(adx_v-20), 120, 280))
        if i>=sw:
            if H[i-sw]>np.max(H[i-sw+1:i+1]): sw_hl=H[i]; sw_hc=False
            if L[i-sw]<np.min(L[i-sw+1:i+1]): sw_ll=L[i]; sw_lc=False
        
        pv=C[i-1] if i>0 else 0
        if not sw_hc and not np.isnan(sw_hl) and pv<=sw_hl and rc>sw_hl:
            sw_hc=True
            sz_hi=H[i]; sz_lo=min(L[max(0,i-50):i+1])
            inv_l=sw_ll if not np.isnan(sw_ll) else sw_hl-3*av; trend=1
        
        if not sw_lc and not np.isnan(sw_ll) and pv>=sw_ll and rc<sw_ll:
            sw_lc=True
            rz_hi=max(H[max(0,i-50):i+1]); rz_lo=L[i]
            inv_s=sw_hl if not np.isnan(sw_hl) else sw_ll+3*av; trend=-1
        
        if trend==1 and not np.isnan(sz_hi):
            if rl<=sz_hi and rc>=sz_lo and rv<=RSI_L:
                last_signal={'direction':'LONG','price':rc,'ob_top':sz_hi,'ob_bottom':sz_lo,'inv':inv_l,'atr':av,'trend':trend}
        
        if trend==-1 and not np.isnan(rz_hi):
            if rh>=rz_lo and rc<=rz_hi and rv>=RSI_S:
                last_signal={'direction':'SHORT','price':rc,'ob_top':rz_hi,'ob_bottom':rz_lo,'inv':inv_s,'atr':av,'trend':trend}
    
    return last_signal

def calc_size(bal,price,atr):
    atr_pct=atr/price
    pct=MAX_POS*min(2.0,VOL_TARGET/max(atr_pct,0.001))
    pct=max(MIN_POS,min(MAX_POS,pct))
    contracts = max(1, int(bal * pct / (price * 0.01)))
    actual_pct = contracts * price * 0.01 / bal
    return contracts, actual_pct

print("=== V4 1m Adaptive Signal ===")
print("Time: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
print("Source: Gate.io BTC_USDT 1m")
print()

df = fetch_1m_bars(500)
if df is not None and len(df) > 0:
    last = df.iloc[-1]
    recent = df.iloc[-5:]
    print("Latest Candle: O=" + f"{last['o']:.1f}" + " H=" + f"{last['h']:.1f}" + " L=" + f"{last['l']:.1f}" + " C=" + f"{last['c']:.1f}" + " V=" + f"{last['v']:.2f}")
    print("Last 5 close: " + " ".join([f"{r['c']:.0f}" for _, r in recent.iterrows()]))
    print("5m Range: " + f"{df['l'].iloc[-5:].min():.1f}" + " - " + f"{df['h'].iloc[-5:].max():.1f}")
    
    tr_arr = np.maximum(df['h'].values-df['l'].values, 
                         np.maximum(abs(df['h'].values-np.roll(df['c'].values,1)),
                                   abs(df['l'].values-np.roll(df['c'].values,1))))
    tr_arr[0] = df['h'].values[0]-df['l'].values[0]
    atr_series = pd.Series(tr_arr).ewm(alpha=1/14,adjust=False).mean().values
    print("ATR(14): " + f"{atr_series[-1]:.1f}" + " (" + f"{atr_series[-1]/last['c']*100:.2f}%" + ")")
    
    delta = pd.Series(df['c'].values).diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean().values
    loss = (-delta).clip(lower=0).ewm(alpha=1/14,adjust=False).mean().values
    rsi_val = 100-100/(1+gain[-1]/(loss[-1]+1e-10))
    print("RSI(14): " + f"{rsi_val:.1f}")

print()

signal = check_signal()
if signal:
    print("SIGNAL: " + signal['direction'] + " @ " + f"{signal['price']:.1f}")
    print("  OB Zone: " + f"{signal['ob_bottom']:.0f}" + " - " + f"{signal['ob_top']:.0f}")
    print("  Invalidation: " + f"{signal['inv']:.1f}")
    print("  ATR: " + f"{signal['atr']:.1f}")
    
    contracts, pct = calc_size(CAPITAL, signal['price'], signal['atr'])
    print("  Position size: " + str(contracts) + " contracts (" + f"{pct*100:.1f}%" + " = $" + f"{CAPITAL*pct:.0f}" + ")")
    
    if signal['direction'] == 'LONG':
        ts = max(signal['ob_bottom'], signal['price'] - ATR_T * signal['atr'])
        print("  Trailing Stop (LONG): " + f"{ts:.1f}" + " (distance: " + f"{signal['price']-ts:.1f}" + " = " + f"{(signal['price']-ts)/signal['price']*100:.2f}%" + ")")
    else:
        ts = min(signal['ob_top'], signal['price'] + ATR_T * signal['atr'])
        print("  Trailing Stop (SHORT): " + f"{ts:.1f}" + " (distance: " + f"{ts-signal['price']:.1f}" + " = " + f"{(ts-signal['price'])/signal['price']*100:.2f}%" + ")")
else:
    print("SIGNAL: None (waiting for swing breakout)")

print()
print("NOTE: OKX API unreachable (DNS poisoned: www.okx.com -> 169.254.0.2)")
print("      Gate.io signal only. Cannot query positions/balance or execute trades.")
