def screen(r,c):
    reasons=[];dv=float(r.DOLLARVOL20);atr=float(r.ATR14);cl=float(r.Close);ap=atr/cl*100 if cl else 999;gp=abs(float(r.GAP))*100 if r.GAP==r.GAP else 0
    if dv<c["minimum_average_dollar_volume_20d"]:reasons.append(f"20d dollar volume ${dv:,.0f}")
    if ap>c["maximum_atr_pct"]:reasons.append(f"ATR% {ap:.1f}")
    if gp>c["maximum_gap_pct"]:reasons.append(f"gap {gp:.1f}%")
    return {"pass":not reasons,"reasons":reasons,"average_dollar_volume_20d":dv,"atr_pct":ap,"gap_pct":gp}
def plan(sig,r,c):
    cl=float(r.Close);atr=float(r.ATR14);st=sig["strategy"]
    if st=="TREND_BREAKOUT":sm,tr=c["trend"]["stop_atr"],c["trend"]["target_r"]
    elif st=="MEAN_REVERSION":sm,tr=c["mean_reversion"]["stop_atr"],c["mean_reversion"]["target_r"]
    else:sm,tr=c["squeeze"]["stop_atr"],c["squeeze"]["target_r"]
    risk=atr*sm;return {"entry_price":cl,"atr14":atr,"stop_loss":cl-risk,"profit_target":cl+risk*tr,"risk_per_unit":risk,"target_r":tr}
