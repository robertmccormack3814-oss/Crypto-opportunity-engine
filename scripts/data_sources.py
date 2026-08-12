import os,time,random
import requests
import pandas as pd
import yfinance as yf
from common import CONFIG

H={"User-Agent":"Mozilla/5.0 Chrome/151 Safari/537.36"}
BINANCE="https://api.binance.com"
CG="https://api.coingecko.com/api/v3"

def binance_supported():
    try:
        r=requests.get(BINANCE+"/api/v3/exchangeInfo",headers=H,timeout=25)
        r.raise_for_status()
        return {s["symbol"] for s in r.json().get("symbols",[]) if s.get("status")=="TRADING"}
    except Exception as e:
        print("Binance exchangeInfo failed:",e)
        return set()

def clean_yahoo_frame(df):
    needed=["Open","High","Low","Close","Volume"]
    if df is None or df.empty:
        return None
    if any(c not in df.columns for c in needed):
        return None
    x=df[needed].copy()
    for c in needed:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna(subset=["Open","High","Low","Close"])
    if len(x)<CONFIG["minimum_history_days"]:
        return None
    x.index=pd.to_datetime(x.index,utc=True)
    return x.tail(450)

def yahoo_batch(assets):
    """
    Fetch the whole slice in one yfinance call instead of one HTTP history
    request per coin. Returns dict symbol -> DataFrame.
    """
    pairs=[]
    by_pair={}
    for a in assets:
        pair=f"{a['symbol']}-USD"
        if pair not in by_pair:
            pairs.append(pair)
            by_pair[pair]=a["symbol"]

    out={}
    if not pairs:
        return out

    try:
        print("Yahoo batch request:",len(pairs),"tickers")
        raw=yf.download(
            pairs,
            period="2y",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False
        )
    except Exception as e:
        print("Yahoo batch download failed:",e)
        return out

    multi=isinstance(raw.columns,pd.MultiIndex)

    for pair in pairs:
        try:
            if multi:
                # group_by=ticker normally places ticker in level 0.
                if pair in raw.columns.get_level_values(0):
                    frame=raw[pair]
                elif pair in raw.columns.get_level_values(-1):
                    frame=raw.xs(pair,axis=1,level=-1)
                else:
                    continue
            else:
                if len(pairs)!=1:
                    continue
                frame=raw

            frame=clean_yahoo_frame(frame)
            if frame is not None:
                out[by_pair[pair]]=frame
        except Exception:
            continue

    print("Yahoo usable histories:",len(out),"/",len(assets))
    return out

def binance_history(pair):
    try:
        r=requests.get(
            BINANCE+"/api/v3/klines",
            params={"symbol":pair,"interval":"1d","limit":300},
            headers=H,timeout=20
        )
        if r.status_code!=200:
            return None

        j=r.json()
        if not isinstance(j,list) or len(j)<CONFIG["minimum_history_days"]:
            return None

        return pd.DataFrame({
            "Date":[pd.to_datetime(x[0],unit="ms",utc=True) for x in j],
            "Open":[float(x[1]) for x in j],
            "High":[float(x[2]) for x in j],
            "Low":[float(x[3]) for x in j],
            "Close":[float(x[4]) for x in j],
            "Volume":[float(x[5]) for x in j]
        }).set_index("Date")
    except Exception:
        return None

def cg_headers():
    h=dict(H)
    key=os.getenv("COINGECKO_DEMO_API_KEY","").strip()
    if key:
        h["x-cg-demo-api-key"]=key
    return h

def has_demo_key():
    return bool(os.getenv("COINGECKO_DEMO_API_KEY","").strip())

def coingecko_history(cid):
    if not cid:
        return None,"No CoinGecko ID"

    # >90 days uses daily auto-granularity per CoinGecko documentation.
    params={"vs_currency":"usd","days":"300","precision":"full"}

    for attempt in range(5):
        try:
            r=requests.get(
                f"{CG}/coins/{cid}/market_chart",
                params=params,
                headers=cg_headers(),
                timeout=35
            )

            if r.status_code==200:
                js=r.json()
                p={}
                v={}
                for ts,val in js.get("prices",[]):
                    d=pd.to_datetime(ts,unit="ms",utc=True).normalize()
                    p[d]=float(val)
                for ts,val in js.get("total_volumes",[]):
                    d=pd.to_datetime(ts,unit="ms",utc=True).normalize()
                    v[d]=float(val)

                idx=sorted(p)
                if len(idx)<CONFIG["minimum_history_days"]:
                    return None,f"CoinGecko only {len(idx)} bars"

                close=pd.Series([p[d] for d in idx],index=idx,dtype=float)
                vol=pd.Series([v.get(d,0.0) for d in idx],index=idx,dtype=float)
                prev=close.shift(1).fillna(close)

                # CoinGecko market_chart is price/volume history, not true daily
                # OHLC. This proxy is explicitly tagged as lower-quality data.
                df=pd.DataFrame({
                    "Open":prev,
                    "High":pd.concat([close,prev],axis=1).max(axis=1),
                    "Low":pd.concat([close,prev],axis=1).min(axis=1),
                    "Close":close,
                    "Volume":vol
                })
                return df,None

            if r.status_code==429:
                wait=max(12,12*(attempt+1))+random.uniform(0.5,2.0)
                print(f"CoinGecko 429 {cid}; backing off {wait:.1f}s")
                time.sleep(wait)
                continue

            if 500<=r.status_code<600:
                wait=5*(attempt+1)
                time.sleep(wait)
                continue

            return None,f"CoinGecko HTTP {r.status_code}"

        except requests.RequestException as e:
            wait=5*(attempt+1)
            print("CoinGecko request error:",cid,e)
            time.sleep(wait)

    return None,"CoinGecko retries exhausted"

def prepare_batch(assets):
    """
    Resolve as much of a scan slice as possible without CoinGecko:
      1) one batched Yahoo call;
      2) Binance for unresolved supported pairs.
    """
    histories={}
    sources={}
    reasons={}

    y=yahoo_batch(assets)
    for a in assets:
        sym=a["symbol"]
        if sym in y:
            histories[sym]=y[sym]
            sources[sym]="Yahoo"
            continue

    supp=binance_supported()
    print("Binance supported pairs:",len(supp))

    for a in assets:
        sym=a["symbol"]
        if sym in histories:
            continue
        pair=a.get("binance_symbol") or (sym+"USDT")
        if pair in supp:
            df=binance_history(pair)
            if df is not None:
                histories[sym]=df
                sources[sym]="Binance"
            else:
                reasons[sym]="Binance history unavailable"
        else:
            reasons[sym]="No Yahoo history and no Binance USDT pair"

    return histories,sources,reasons
