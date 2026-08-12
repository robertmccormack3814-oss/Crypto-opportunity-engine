import os,json,smtplib,time,requests,pandas as pd
from email.message import EmailMessage
from common import DATA,CONFIG,load_json,save_json,now_iso
from indicators import compute
from engine import classify,route,flow
from data_sources import prepare_batch,coingecko_history,has_demo_key
from risk import screen,plan

def emit(kind,p):
    if CONFIG["alerts"]["enable_email"]:
        u=os.getenv("SMTP_USERNAME","").strip()
        pw=os.getenv("SMTP_APP_PASSWORD","").strip()
        to=CONFIG["alerts"]["email_to"].strip()
        if u and pw:
            m=EmailMessage()
            m["From"]=u;m["To"]=to
            m["Subject"]=f"CRYPTO {kind}: {p.get('symbol')} {p.get('strategy','')}"
            m.set_content(json.dumps(p,indent=2))
            with smtplib.SMTP("smtp.gmail.com",587,timeout=30) as s:
                s.starttls();s.login(u,pw);s.send_message(m)

    url=os.getenv("ALERT_WEBHOOK_URL","").strip()
    if CONFIG["alerts"]["enable_webhook"] and url:
        try:
            requests.post(url,json={"type":kind.lower(),"payload":p},timeout=20)
        except Exception as e:
            print("Webhook error:",e)

def exit_check(tr,x):
    r=x.iloc[-1]
    low=float(r.Low);high=float(r.High);cl=float(r.Close)
    days=sum(x.index.date>pd.Timestamp(tr["entry_date"]).date())

    if low<=tr["stop_loss"]:
        return "STOP_LOSS",tr["stop_loss"]
    if high>=tr["profit_target"]:
        return "PROFIT_TARGET",tr["profit_target"]

    if tr["strategy"]=="TREND_BREAKOUT":
        atr=float(r.ATR14)
        peak=max(tr.get("peak_price",tr["entry_price"]),high)
        tr["peak_price"]=peak
        trail=peak-CONFIG["exit"]["trend_trailing_atr"]*atr
        tr["trailing_stop"]=max(tr.get("trailing_stop",tr["stop_loss"]),trail)
        if low<=tr["trailing_stop"]:
            return "ATR_TRAILING_STOP",tr["trailing_stop"]

    if days>=CONFIG["exit"]["max_holding_days"]:
        return "TIME_EXIT",cl

    return None,None

def keep_error_or_stale(assets,item,reason):
    sym=item["symbol"]
    prior=assets.get(sym)

    if prior and prior.get("status")=="ok":
        prior=dict(prior)
        prior["data_status"]="STALE"
        prior["data_error"]=reason
        prior["last_attempt_at"]=now_iso()
        assets[sym]=prior
        return "STALE"

    assets[sym]={
        "symbol":sym,
        "name":item["name"],
        "status":"error",
        "data_status":"ERROR",
        "data_error":reason,
        "reason":reason,
        "last_attempt_at":now_iso()
    }
    return "ERROR"

def main():
    u=load_json(DATA/"universe.json",[])
    if not u:
        raise RuntimeError("Universe empty. Run build_universe.py first.")

    cur=load_json(DATA/"cursor.json",{"next_index":0})
    st=load_json(DATA/"state.json",{"active_trades":{},"closed_trades":[]})
    active=st.get("active_trades",{})
    closed=st.get("closed_trades",[])

    old=load_json(DATA/"scanner.json",{})
    assets={x.get("symbol"):x for x in old.get("assets",[]) if x.get("symbol")}

    start=int(cur.get("next_index",0))%len(u)
    batch_size=int(CONFIG.get("batch_size",60))
    items=[u[(start+i)%len(u)] for i in range(min(batch_size,len(u)))]

    # Fetch Yahoo in one batch and Binance only for unresolved supported pairs.
    histories,sources,base_reasons=prepare_batch(items)

    # CoinGecko is now a last resort with a hard request budget.
    demo=has_demo_key()
    cg_budget=int(CONFIG.get("coingecko_max_requests_per_run",20 if demo else 5))
    if not demo:
        # Keyless public CoinGecko is a shared IP pool. Keep the budget tiny.
        cg_budget=min(cg_budget,5)

    print("CoinGecko demo key configured:",demo)
    print("CoinGecko fallback budget:",cg_budget)

    cg_used=0
    signals=[]
    exits=[]
    errs=0
    proc=0
    stale_count=0

    for n,item in enumerate(items,1):
        sym=item["symbol"]
        x=histories.get(sym)
        src=sources.get(sym)
        reason=base_reasons.get(sym,"No primary history")

        if x is None and cg_used<cg_budget:
            cg_used+=1
            x,cg_reason=coingecko_history(item.get("coingecko_id"))
            if x is not None:
                src="CoinGecko fallback"
            elif cg_reason:
                reason=reason+" | "+cg_reason

            # Always pace fallback requests.
            time.sleep(float(CONFIG.get("coingecko_delay_seconds",4.0)))

        elif x is None and cg_used>=cg_budget:
            reason=reason+" | CoinGecko fallback deferred to avoid rate limit"

        if x is None:
            status=keep_error_or_stale(assets,item,reason)
            if status=="STALE":
                stale_count+=1
            errs+=1
            print(f"[{n}/{len(items)}] {sym} -> {status}: {reason}")
            continue

        z=compute(x).dropna(subset=["ATR14","ADX14","EMA200","ZS20","BBWIDTH"])

        if len(z)<5:
            reason=f"Only {len(z)} usable indicator rows from {src}"
            status=keep_error_or_stale(assets,item,reason)
            if status=="STALE":
                stale_count+=1
            errs+=1
            continue

        r=z.iloc[-1]
        proc+=1
        rg,meta=classify(z,CONFIG)
        fs=flow(r)

        if sym in active:
            why,px=exit_check(active[sym],z)
            if why:
                tr=active.pop(sym)
                payload={
                    **tr,
                    "exit_date":str(z.index[-1].date()),
                    "exit_price":px,
                    "exit_reason":why,
                    "pnl_pct":((px/tr["entry_price"])-1)*100
                }
                exits.append(payload);closed.append(payload);emit("EXIT",payload)

        sig=route(z,rg,CONFIG)
        cand=None

        if sig and sym not in active:
            sig["score"]=min(100,sig["score"]+max(-10,(fs-50)*.2))
            sc=screen(r,CONFIG)
            pl=plan(sig,r,CONFIG)

            payload={
                "symbol":sym,"name":item["name"],
                "strategy":sig["strategy"],"direction":sig["direction"],
                "regime":rg,"signal_score":round(sig["score"],1),
                "flow_score":round(fs,1),"reasons":sig["reasons"],
                "regime_details":meta,"execution_risk":sc,**pl,
                "data_source":src,
                "data_quality":"FULL_OHLCV" if src in ("Yahoo","Binance") else "DAILY_PROXY",
                "signal_date":str(z.index[-1].date()),
                "timestamp":now_iso()
            }

            # CoinGecko proxy data may classify regimes, but only full OHLCV
            # sources are allowed to create an actionable breakout/squeeze trade.
            full_ohlcv=src in ("Yahoo","Binance")
            actionable = (
                sig["score"]>=CONFIG["minimum_signal_score"]
                and sc["pass"]
                and (full_ohlcv or sig["strategy"]=="MEAN_REVERSION")
            )

            if actionable:
                active[sym]={
                    **payload,
                    "entry_date":payload["signal_date"],
                    "peak_price":payload["entry_price"],
                    "trailing_stop":payload["stop_loss"]
                }
                signals.append(payload);emit("ENTRY",payload);cand=payload
            elif sig["score"]>=CONFIG["minimum_signal_score"]:
                reject_reason=[]
                if not sc["pass"]:
                    reject_reason+=sc["reasons"]
                if not full_ohlcv and sig["strategy"]!="MEAN_REVERSION":
                    reject_reason.append("Full OHLCV required for breakout/squeeze")
                cand={**payload,"rejected":True,"rejection_reasons":reject_reason}

        assets[sym]={
            "symbol":sym,"name":item["name"],"status":"ok",
            "data_status":"LIVE","data_error":None,
            "data_source":src,
            "data_quality":"FULL_OHLCV" if src in ("Yahoo","Binance") else "DAILY_PROXY",
            "regime":rg,"price_usd":float(r.Close),
            "adx14":float(r.ADX14),
            "relative_volume":float(r.RELVOL20) if pd.notna(r.RELVOL20) else None,
            "zscore20":float(r.ZS20),"flow_score":round(fs,1),
            "active":sym in active,"candidate":cand,"updated_at":now_iso()
        }
        print(f"[{n}/{len(items)}] {sym} -> OK {src} {rg}")

    nxt=(start+len(items))%len(u)

    save_json(DATA/"cursor.json",{"next_index":nxt,"last_run":now_iso()})
    save_json(DATA/"state.json",{
        "active_trades":active,
        "closed_trades":closed[-500:],
        "updated_at":now_iso()
    })

    stats={
        "universe":len(u),
        "known_assets":len(assets),
        "live_assets":sum(1 for x in assets.values() if x.get("status")=="ok" and x.get("data_status")=="LIVE"),
        "stale_assets":sum(1 for x in assets.values() if x.get("data_status")=="STALE"),
        "data_errors_total":sum(1 for x in assets.values() if x.get("status")=="error"),
        "active_trades":len(active),
        "signals_this_batch":len(signals),
        "exits_this_batch":len(exits),
        "batch_processed":proc,
        "batch_errors":errs,
        "stale_kept_this_batch":stale_count,
        "coingecko_requests_this_batch":cg_used,
        "next_index":nxt
    }

    save_json(DATA/"scanner.json",{
        "generated_at":now_iso(),"stats":stats,
        "signals":signals,"exits":exits,
        "active_trades":sorted(active.values(),key=lambda x:x["symbol"]),
        "assets":sorted(assets.values(),key=lambda x:(0 if x.get("active") else 1,0 if x.get("status")=="ok" else 1,x.get("symbol","")))
    })
    print(stats)

if __name__=="__main__":
    main()
