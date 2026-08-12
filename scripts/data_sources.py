import os,time,requests,pandas as pd
from common import CONFIG
H={"User-Agent":"Mozilla/5.0 Chrome/151 Safari/537.36"}
def supported():
    try:
        r=requests.get("https://api.binance.com/api/v3/exchangeInfo",headers=H,timeout=30);r.raise_for_status()
        return {s["symbol"] for s in r.json().get("symbols",[]) if s.get("status")=="TRADING"}
    except:return set()
def binance(sym):
    try:
        r=requests.get("https://api.binance.com/api/v3/klines",params={"symbol":sym,"interval":"1d","limit":300},headers=H,timeout=20)
        if r.status_code!=200:return None
        j=r.json()
        if len(j)<CONFIG["minimum_history_days"]:return None
        return pd.DataFrame({"Date":[pd.to_datetime(x[0],unit="ms",utc=True) for x in j],"Open":[float(x[1]) for x in j],"High":[float(x[2]) for x in j],"Low":[float(x[3]) for x in j],"Close":[float(x[4]) for x in j],"Volume":[float(x[5]) for x in j]}).set_index("Date")
    except:return None
def cg(cid):
    if not cid:return None,"No CoinGecko ID"
    h=dict(H);k=os.getenv("COINGECKO_DEMO_API_KEY","").strip()
    if k:h["x-cg-demo-api-key"]=k
    try:
        r=requests.get(f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart",params={"vs_currency":"usd","days":"300","interval":"daily"},headers=h,timeout=30)
        if r.status_code!=200:return None,f"CoinGecko HTTP {r.status_code}"
        js=r.json();p={};v={}
        for ts,x in js.get("prices",[]):p[pd.to_datetime(ts,unit="ms",utc=True).normalize()]=float(x)
        for ts,x in js.get("total_volumes",[]):v[pd.to_datetime(ts,unit="ms",utc=True).normalize()]=float(x)
        idx=sorted(p)
        if len(idx)<CONFIG["minimum_history_days"]:return None,f"Only {len(idx)} bars"
        close=pd.Series([p[d] for d in idx],index=idx);vol=pd.Series([v.get(d,0) for d in idx],index=idx)
        df=pd.DataFrame({"Open":close.shift(1).fillna(close),"High":pd.concat([close,close.shift(1)],axis=1).max(axis=1),"Low":pd.concat([close,close.shift(1)],axis=1).min(axis=1),"Close":close,"Volume":vol})
        return df,None
    except Exception as e:return None,str(e)
