#!/usr/bin/env python3
"""V4 1m 持久运行 — 每分钟检查, 跑5.5小时后退出让GitHub重启"""
import subprocess, json, time as t, hmac, base64, hashlib, os
from datetime import datetime, timezone
import pandas as pd, numpy as np

OKX_KEY = os.environ["OKX_API_KEY"]
OKX_SECRET = os.environ["OKX_SECRET"]
OKX_PASS = os.environ["OKX_PASSPHRASE"]
DEMO = False
INST = "BTC-USDT-SWAP"
SWING=200; ATR_T=2.5; RSI_L=60; RSI_S=40
RUN_HOURS=0.9; MAX_POS=0.20; MIN_POS=0.02; VOL_T=0.015

def okx_req(method, path, body=""):
    ts=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+'Z'
    s=base64.b64encode(hmac.new(OKX_SECRET.encode(),(ts+method.upper()+path+body).encode(),hashlib.sha256).digest()).decode()
    hdrs={'OK-ACCESS-KEY':OKX_KEY,'OK-ACCESS-SIGN':s,'OK-ACCESS-TIMESTAMP':ts,'OK-ACCESS-PASSPHRASE':OKX_PASS,'Content-Type':'application/json'}
    if method=='GET':
        r=subprocess.run(['curl','-s',f'https://www.okx.com{path}']+[f'-H{k}:{v}' for k,v in hdrs.items()],capture_output=True,text=True,timeout=15)
    else:
        r=subprocess.run(['curl','-s','-X',method,f'https://www.okx.com{path}','-d',body]+[f'-H{k}:{v}' for k,v in hdrs.items()],capture_output=True,text=True,timeout=15)
    return json.loads(r.stdout) if r.stdout else {}

def get_pos():
    r=okx_req('GET',f'/api/v5/account/positions?instId={INST}')
    return [p for p in r.get('data',[]) if float(p.get('pos',0))>0] if r.get('code')=='0' else []

def get_bal():
    r=okx_req('GET','/api/v5/account/balance')
    if r.get('code')=='0':
        for d in r['data']:
            for det in d.get('details',[]):
                if det['ccy']=='USDT': return float(det.get('availEq',0))
    return 0

def place(side,sz,ps):
    order={'instId':INST,'tdMode':'cross','side':side,'ordType':'market','sz':str(sz)}
    if ps: order['posSide']=ps
    return okx_req('POST','/api/v5/trade/order',json.dumps(order))

def close_pos(side,sz):
    return okx_req('POST','/api/v5/trade/order',json.dumps({'instId':INST,'tdMode':'cross','side':side,'ordType':'market','sz':str(sz),'posSide':'long' if side=='sell' else 'short'}))

def fetch_bars(limit=500):
    try:
        r=subprocess.run(['curl','-s',f'https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=BTC_USDT&interval=1m&limit={limit}'],capture_output=True,text=True,timeout=15)
        data=json.loads(r.stdout)
        if not isinstance(data,list): return None
        rows=[{'t':int(p[0]),'o':float(p[5]),'h':float(p[3]),'l':float(p[4]),'c':float(p[2]),'v':float(p[1])} for p in data]
        return pd.DataFrame(rows).sort_values('t').reset_index(drop=True)
    except: return None

def check_signal():
    df=fetch_bars(500)
    if df is None or len(df)<SWING*2: return None
    n=len(df); H=df['h'].values; L=df['l'].values; C=df['c'].values
    tr=np.maximum(H-L,np.maximum(abs(H-np.roll(C,1)),abs(L-np.roll(C,1)))); tr[0]=H[0]-L[0]
    atr=pd.Series(tr).ewm(alpha=1/14,adjust=False).mean().values
    delta=pd.Series(C).diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean().values
    lss=(-delta).clip(lower=0).ewm(alpha=1/14,adjust=False).mean().values; rsi=100-100/(1+gain/(lss+1e-10))
    
    sw_hl=np.nan; sw_ll=np.nan; sw_hc=True; sw_lc=True; trend=0
    sz_hi=np.nan; sz_lo=np.nan; rz_hi=np.nan; rz_lo=np.nan
    inv_l=np.nan; inv_s=np.nan; lbu=-999; lbd=-999; lcu=-999; lcd=-999; ls=None
    
    # 完整leg数组(与回测一致)
    leg=np.zeros(n,dtype=int)
    for i in range(SWING,n):
        if H[i-SWING]>np.max(H[i-SWING+1:i+1]): leg[i]=0
        elif L[i-SWING]<np.min(L[i-SWING+1:i+1]): leg[i]=1
        else: leg[i]=leg[i-1]
    dleg=np.diff(leg,prepend=leg[0]); sw_high,sw_low=dleg==-1,dleg==1
    
    for i in range(SWING,n):
        rh,rl,rc=H[i],L[i],C[i]; av=atr[i]; rv=rsi[i] if not np.isnan(rsi[i]) else 50
        if sw_high[i]: sw_hl=H[i]; sw_hc=False
        if sw_low[i]: sw_ll=L[i]; sw_lc=False
        pv=C[i-1] if i>0 else 0
        if not sw_hc and not np.isnan(sw_hl) and pv<=sw_hl and rc>sw_hl:
            sw_hc=True
            if trend==-1: lcu=i
            else: lbu=i
            sz_hi=H[i]; sz_lo=min(L[max(0,i-50):i+1]); inv_l=sw_ll if not np.isnan(sw_ll) else sw_hl-3*av; trend=1
        if not sw_lc and not np.isnan(sw_ll) and pv>=sw_ll and rc<sw_ll:
            sw_lc=True
            if trend==1: lcd=i
            else: lbd=i
            rz_hi=max(H[max(0,i-50):i+1]); rz_lo=L[i]; inv_s=sw_hl if not np.isnan(sw_hl) else sw_ll+3*av; trend=-1
        if trend==1 and not np.isnan(sz_hi) and rl<=sz_hi and rc>=sz_lo and rv<=RSI_L:
            ls={'direction':'LONG','price':rc,'ob_top':sz_hi,'ob_bottom':sz_lo,'inv':inv_l,'atr':av}
        if trend==-1 and not np.isnan(rz_hi) and rh>=rz_lo and rc<=rz_hi and rv>=RSI_S:
            ls={'direction':'SHORT','price':rc,'ob_top':rz_hi,'ob_bottom':rz_lo,'inv':inv_s,'atr':av}
    return ls

def calc_size(bal,price,atr):
    atr_pct=atr/price; pct=MAX_POS*min(2.0,VOL_T/max(atr_pct,0.001))
    pct=max(MIN_POS,min(MAX_POS,pct))
    contracts=max(1,int(bal*pct/(price*0.01)))
    return contracts, contracts*price*0.01/bal

def run_once():
    sig=check_signal(); pos=get_pos(); bal=get_bal()
    t.now().strftime('%H:%M:%S')
    
    if sig:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {sig['direction']} @ {sig['price']:.0f} OB:{sig['ob_bottom']:.0f}~{sig['ob_top']:.0f}")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 无信号")
    
    # 移动止损
    if pos and sig:
        df=fetch_bars(5)
        if df is not None and len(df)>=2:
            curr=df['c'].iloc[-1]; cl=df['l'].iloc[-1]; ch=df['h'].iloc[-1]
            av=sig.get('atr',curr*0.002)
            for p in pos:
                if p['posSide']=='long':
                    ts=max(sig.get('ob_bottom',curr-ATR_T*av),curr-ATR_T*av); hit=cl<=ts
                else:
                    ts=min(sig.get('ob_top',curr+ATR_T*av),curr+ATR_T*av); hit=ch>=ts
                if hit:
                    cs='sell' if p['posSide']=='long' else 'buy'
                    r=close_pos(cs,p['pos'])
                    print(f"  🛑 止损@{ts:.0f} {'✅' if r.get('code')=='0' else '❌'+str(r.get('msg',''))}")
    
    # 反转/入场
    if sig and pos:
        sd='long' if sig['direction']=='LONG' else 'short'
        for p in pos:
            if p['posSide']!=sd:
                cs='sell' if p['posSide']=='long' else 'buy'
                r=close_pos(cs,p['pos'])
                if r.get('code')=='0':
                    sz,pct=calc_size(bal,sig['price'],sig.get('atr',sig['price']*0.005))
                    r2=place('buy' if sig['direction']=='LONG' else 'sell',sz,'long' if sig['direction']=='LONG' else 'short')
                    print(f"  🔄 反转 {sig['direction']} {sz}张 {'✅' if r2.get('code')=='0' else '❌'}")
    elif sig and not pos:
        sz,pct=calc_size(bal,sig['price'],sig.get('atr',sig['price']*0.005))
        r=place('buy' if sig['direction']=='LONG' else 'sell',sz,'long' if sig['direction']=='LONG' else 'short')
        print(f"  🔔 {sig['direction']} {sz}张 @ {sig['price']:.0f} {'✅' if r.get('code')=='0' else '❌'+str(r.get('msg',''))}")

if __name__=='__main__':
    deadline=t.time()+RUN_HOURS*3600
    print(f"V4持久运行 启动 (跑{RUN_HOURS}小时)")
    while t.time()<deadline:
        try: run_once()
        except Exception as e: print(f"异常: {e}")
        t.sleep(60)
    print("时间到, 等待GitHub重启")
