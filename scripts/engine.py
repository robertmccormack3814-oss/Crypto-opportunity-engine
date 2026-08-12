import pandas as pd
from indicators import pctlast
def classify(x,c):
    r=x.iloc[-1];adx=float(r.ADX14);bb=pctlast(x.BBWIDTH,120);up=float(r.Close)>float(r.EMA20)>float(r.EMA50)>float(r.EMA200)
    if pd.notna(bb) and bb<=c["squeeze"]["bb_width_percentile_max"]:return "SQUEEZE",{"bb_width_percentile":bb}
    if adx>=c["trend"]["adx_min"] and up:return "TREND",{"adx":adx}
    if adx<=c["mean_reversion"]["adx_max"]:return "RANGE",{"adx":adx}
    return "UNCLEAR",{"adx":adx,"bb_width_percentile":bb}
def flow(r):
    rel=float(r.RELVOL20) if pd.notna(r.RELVOL20) else 0;clv=float(r.CLV) if pd.notna(r.CLV) else .5;svp=float(r.SVP10) if pd.notna(r.SVP10) else 0
    return max(0,min(100,50+min(20,max(-10,(rel-1)*20))+(clv-.5)*20+max(-15,min(15,svp*30))))
def route(x,rg,c):
    r=x.iloc[-1];rel=float(r.RELVOL20) if pd.notna(r.RELVOL20) else 0;score=0;why=[]
    if rg=="TREND":
        br=float(r.Close)>float(r.HIGH20_PREV)
        if br:score+=30;why.append("20-day breakout")
        if float(r.Close)>float(r.EMA20)>float(r.EMA50)>float(r.EMA200):score+=20;why.append("EMA alignment")
        if float(r.ADX14)>=c["trend"]["adx_min"]:score+=20;why.append(f"ADX {float(r.ADX14):.1f}")
        if rel>=c["trend"]["relative_volume_min"]:score+=20;why.append(f"relative volume {rel:.2f}x")
        if float(r.CLV)>=.65:score+=10;why.append("strong close")
        if br and score>=c["minimum_signal_score"]:return {"direction":"LONG","strategy":"TREND_BREAKOUT","score":score,"reasons":why}
    if rg=="RANGE":
        z=float(r.ZS20);rr=float(r.RSI5)
        if z<=c["mean_reversion"]["zscore_entry"]:score+=35;why.append(f"z-score {z:.2f}")
        if rr<=c["mean_reversion"]["rsi5_max"]:score+=25;why.append(f"RSI5 {rr:.1f}")
        if float(r.ADX14)<=c["mean_reversion"]["adx_max"]:score+=20;why.append("range ADX")
        if float(r.CLV)>=.3:score+=10;why.append("not closing on low")
        if float(r.SVP10)>-.75:score+=10;why.append("selling pressure moderating")
        if z<0 and score>=c["minimum_signal_score"]:return {"direction":"LONG","strategy":"MEAN_REVERSION","score":score,"reasons":why}
    if rg=="SQUEEZE":
        bb=pctlast(x.BBWIDTH,120);br=float(r.Close)>float(r.HIGH20_PREV)
        if pd.notna(bb) and bb<=c["squeeze"]["bb_width_percentile_max"]:score+=35;why.append(f"BB width pct {bb:.0f}")
        if rel>=c["squeeze"]["relative_volume_breakout_min"]:score+=25;why.append(f"relative volume {rel:.2f}x")
        if br:score+=25;why.append("compression breakout")
        if float(r.CLV)>=.7:score+=15;why.append("strong close")
        if br and score>=c["minimum_signal_score"]:return {"direction":"LONG","strategy":"SQUEEZE_EXPANSION","score":score,"reasons":why}
