import os,json,smtplib,time,requests,pandas as pd
from email.message import EmailMessage
from common import DATA,CONFIG,load_json,save_json,now_iso
from indicators import compute
from engine import classify,route,flow
from data_sources import supported,binance,cg
from risk import screen,plan
def emit(kind,p):
    if CONFIG["alerts"]["enable_email"]:
        u=os.getenv("SMTP_USERNAME","").strip();pw=os.getenv("SMTP_APP_PASSWORD","").strip();to=CONFIG["alerts"]["email_to"].strip()
        if u and pw:
            m=EmailMessage();m["From"]=u;m["To"]=to;m["Subject"]=f"CRYPTO {kind}: {p.get('symbol')} {p.get('strategy','')}";m.set_content(json.dumps(p,indent=2))
            with smtplib.SMTP("smtp.gmail.com",587,timeout=30) as s:s.starttls();s.login(u,pw);s.send_message(m)
    url=os.getenv("ALERT_WEBHOOK_URL","").strip()
    if CONFIG["alerts"]["enable_webhook"] and url:
        try:requests.post(url,json={"type":kind.lower(),"payload":p},timeout=20)
        except:pass
def exit_check(tr,x):
    r=x.iloc[-1];low=float(r.Low);high=float(r.High);cl=float(r.Close);days=sum(x.index.date>pd.Timestamp(tr["entry_date"]).date())
    if low<=tr["stop_loss"]:return "STOP_LOSS",tr["stop_loss"]
    if high>=tr["profit_target"]:return "PROFIT_TARGET",tr["profit_target"]
    if tr["strategy"]=="TREND_BREAKOUT":
        atr=float(r.ATR14);peak=max(tr.get("peak_price",tr["entry_price"]),high);tr["peak_price"]=peak;trail=peak-CONFIG["exit"]["trend_trailing_atr"]*atr;tr["trailing_stop"]=max(tr.get("trailing_stop",tr["stop_loss"]),trail)
        if low<=tr["trailing_stop"]:return "ATR_TRAILING_STOP",tr["trailing_stop"]
    if days>=CONFIG["exit"]["max_holding_days"]:return "TIME_EXIT",cl
    return None,None
def main():
    u=load_json(DATA/"universe.json",[]);cur=load_json(DATA/"cursor.json",{"next_index":0});st=load_json(DATA/"state.json",{"active_trades":{},"closed_trades":[]});active=st["active_trades"];closed=st["closed_trades"];old=load_json(DATA/"scanner.json",{});assets={x.get("symbol"):x for x in old.get("assets",[]) if x.get("symbol")}
    start=int(cur.get("next_index",0))%len(u);items=[u[(start+i)%len(u)] for i in range(min(CONFIG["batch_size"],len(u)))];supp=supported();signals=[];exits=[];errs=proc=0
    for item in items:
        sym=item["symbol"];x=None;src=None;reason=None
        if item.get("binance_symbol") in supp:
            x=binance(item["binance_symbol"]);src="Binance" if x is not None else None
        if x is None:
            x,reason=cg(item.get("coingecko_id"));src="CoinGecko fallback" if x is not None else None
        if x is None:
            assets[sym]={"symbol":sym,"name":item["name"],"status":"error","reason":reason or "No history"};errs+=1;continue
        z=compute(x).dropna(subset=["ATR14","ADX14","EMA200","ZS20","BBWIDTH"])
        if len(z)<5:
            assets[sym]={"symbol":sym,"name":item["name"],"status":"error","reason":"Insufficient indicator rows"};errs+=1;continue
        r=z.iloc[-1];proc+=1;rg,meta=classify(z,CONFIG);fs=flow(r)
        if sym in active:
            why,px=exit_check(active[sym],z)
            if why:
                tr=active.pop(sym);payload={**tr,"exit_date":str(z.index[-1].date()),"exit_price":px,"exit_reason":why,"pnl_pct":((px/tr["entry_price"])-1)*100};exits.append(payload);closed.append(payload);emit("EXIT",payload)
        sig=route(z,rg,CONFIG);cand=None
        if sig and sym not in active:
            sig["score"]=min(100,sig["score"]+max(-10,(fs-50)*.2));sc=screen(r,CONFIG);pl=plan(sig,r,CONFIG)
            payload={"symbol":sym,"name":item["name"],"strategy":sig["strategy"],"direction":sig["direction"],"regime":rg,"signal_score":round(sig["score"],1),"flow_score":round(fs,1),"reasons":sig["reasons"],"regime_details":meta,"execution_risk":sc,**pl,"data_source":src,"signal_date":str(z.index[-1].date()),"timestamp":now_iso()}
            if sig["score"]>=CONFIG["minimum_signal_score"] and sc["pass"]:
                active[sym]={**payload,"entry_date":payload["signal_date"],"peak_price":payload["entry_price"],"trailing_stop":payload["stop_loss"]};signals.append(payload);emit("ENTRY",payload);cand=payload
            elif sig["score"]>=CONFIG["minimum_signal_score"]:cand={**payload,"rejected":True}
        assets[sym]={"symbol":sym,"name":item["name"],"status":"ok","regime":rg,"price_usd":float(r.Close),"adx14":float(r.ADX14),"relative_volume":float(r.RELVOL20) if pd.notna(r.RELVOL20) else None,"zscore20":float(r.ZS20),"flow_score":round(fs,1),"active":sym in active,"candidate":cand,"data_source":src,"updated_at":now_iso()}
        if src=="CoinGecko fallback":time.sleep(CONFIG["coingecko_delay_seconds"])
    nxt=(start+len(items))%len(u);save_json(DATA/"cursor.json",{"next_index":nxt,"last_run":now_iso()});save_json(DATA/"state.json",{"active_trades":active,"closed_trades":closed[-500:],"updated_at":now_iso()})
    stats={"universe":len(u),"known_assets":len(assets),"active_trades":len(active),"signals_this_batch":len(signals),"exits_this_batch":len(exits),"batch_processed":proc,"batch_errors":errs,"next_index":nxt}
    save_json(DATA/"scanner.json",{"generated_at":now_iso(),"stats":stats,"signals":signals,"exits":exits,"active_trades":sorted(active.values(),key=lambda x:x["symbol"]),"assets":sorted(assets.values(),key=lambda x:(0 if x.get("active") else 1,x.get("symbol","")))});print(stats)
if __name__=="__main__":main()
