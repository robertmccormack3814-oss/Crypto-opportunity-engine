import os, time, random
import requests
import pandas as pd
import yfinance as yf
from common import CONFIG

H={"User-Agent":"Mozilla/5.0 Chrome/151 Safari/537.36"}
BINANCE="https://api.binance.com"
COINGECKO="https://api.coingecko.com/api/v3"

def supported():
    try:
        r=requests.get(
            BINANCE+"/api/v3/exchangeInfo",
            headers=H,
            timeout=20
        )
        if r.status_code!=200:
            print("Binance exchangeInfo HTTP",r.status_code)
            return set()
        return {
            s["symbol"]
            for s in r.json().get("symbols",[])
            if s.get("status")=="TRADING"
        }
    except Exception as e:
        print("Binance exchangeInfo error:",e)
        return set()

def binance(sym):
    try:
        r=requests.get(
            BINANCE+"/api/v3/klines",
            params={"symbol":sym,"interval":"1d","limit":300},
            headers=H,
            timeout=20
        )
        if r.status_code!=200:
            return None,f"Binance HTTP {r.status_code}"

        j=r.json()
        if not isinstance(j,list):
            return None,"Unexpected Binance response"
        if len(j)<CONFIG["minimum_history_days"]:
            return None,f"Binance only {len(j)} bars"

        df=pd.DataFrame({
            "Date":[pd.to_datetime(x[0],unit="ms",utc=True) for x in j],
            "Open":[float(x[1]) for x in j],
            "High":[float(x[2]) for x in j],
            "Low":[float(x[3]) for x in j],
            "Close":[float(x[4]) for x in j],
            "Volume":[float(x[5]) for x in j]
        }).set_index("Date")

        return df,None
    except Exception as e:
        return None,f"Binance error: {e}"

def yahoo(sym):
    """
    Yahoo often exposes crypto as SYMBOL-USD. This is an independent
    OHLCV fallback, useful when Binance is unavailable to the runner
    or the asset does not have a Binance USDT market.
    """
    ticker=f"{sym}-USD"
    try:
        df=yf.download(
            ticker,
            period="2y",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False
        )
        if df is None or df.empty:
            return None,"Yahoo no data"

        # yfinance can return one-level or MultiIndex columns.
        if isinstance(df.columns,pd.MultiIndex):
            try:
                df=df.xs(ticker,axis=1,level=1)
            except Exception:
                df.columns=df.columns.get_level_values(0)

        needed=["Open","High","Low","Close","Volume"]
        if any(c not in df.columns for c in needed):
            return None,"Yahoo missing OHLCV columns"

        out=df[needed].copy()
        for c in needed:
            out[c]=pd.to_numeric(out[c],errors="coerce")
        out=out.dropna(subset=["Open","High","Low","Close"])

        if len(out)<CONFIG["minimum_history_days"]:
            return None,f"Yahoo only {len(out)} bars"

        # Keep UTC-compatible index.
        out.index=pd.to_datetime(out.index,utc=True)
        return out.tail(400),None

    except Exception as e:
        return None,f"Yahoo error: {e}"

def cg_headers():
    h=dict(H)
    key=os.getenv("COINGECKO_DEMO_API_KEY","").strip()
    if key:
        h["x-cg-demo-api-key"]=key
    return h

def cg(cid):
    if not cid:
        return None,"No CoinGecko ID"

    # Do NOT force interval=daily. For >90 days CoinGecko automatically
    # supplies daily granularity, which is compatible with more API tiers.
    params={
        "vs_currency":"usd",
        "days":"300",
        "precision":"full"
    }

    for attempt in range(5):
        try:
            r=requests.get(
                f"{COINGECKO}/coins/{cid}/market_chart",
                params=params,
                headers=cg_headers(),
                timeout=30
            )

            if r.status_code==200:
                js=r.json()
                prices={}
                vols={}

                for ts,x in js.get("prices",[]):
                    d=pd.to_datetime(ts,unit="ms",utc=True).normalize()
                    prices[d]=float(x)

                for ts,x in js.get("total_volumes",[]):
                    d=pd.to_datetime(ts,unit="ms",utc=True).normalize()
                    vols[d]=float(x)

                idx=sorted(prices)
                if len(idx)<CONFIG["minimum_history_days"]:
                    return None,f"CoinGecko only {len(idx)} bars"

                close=pd.Series([prices[d] for d in idx],index=idx,dtype=float)
                volume=pd.Series([vols.get(d,0.0) for d in idx],index=idx,dtype=float)

                # Market-chart provides daily price/volume, not full candles.
                # Create conservative proxy OHLC from adjacent daily closes.
                prev=close.shift(1).fillna(close)
                df=pd.DataFrame({
                    "Open":prev,
                    "High":pd.concat([close,prev],axis=1).max(axis=1),
                    "Low":pd.concat([close,prev],axis=1).min(axis=1),
                    "Close":close,
                    "Volume":volume
                })
                return df,None

            if r.status_code==429:
                wait=min(50,7*(attempt+1))+random.uniform(.5,1.5)
                print(f"CoinGecko 429 {cid}: wait {wait:.1f}s")
                time.sleep(wait)
                continue

            if 500<=r.status_code<600:
                wait=3*(attempt+1)+random.uniform(.2,.8)
                time.sleep(wait)
                continue

            return None,f"CoinGecko HTTP {r.status_code}"

        except requests.RequestException as e:
            wait=3*(attempt+1)
            print("CoinGecko request error:",cid,e)
            time.sleep(wait)

    return None,"CoinGecko retries exhausted"

def get_history(asset, binance_symbols):
    """
    Robust hierarchy:
      1. Binance OHLCV when the pair exists.
      2. Yahoo SYMBOL-USD OHLCV.
      3. CoinGecko daily price/volume proxy.
    """
    errors=[]

    bpair=asset.get("binance_symbol")
    if bpair and bpair in binance_symbols:
        df,err=binance(bpair)
        if df is not None:
            return df,"Binance",None
        if err:
            errors.append(err)

    df,err=yahoo(asset["symbol"])
    if df is not None:
        return df,"Yahoo",None
    if err:
        errors.append(err)

    df,err=cg(asset.get("coingecko_id"))
    if df is not None:
        return df,"CoinGecko fallback",None
    if err:
        errors.append(err)

    return None,None," | ".join(errors[-3:]) or "No usable market data"
