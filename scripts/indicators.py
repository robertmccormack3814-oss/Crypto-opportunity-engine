import numpy as np,pandas as pd
def ema(s,n):return s.ewm(span=n,adjust=False).mean()
def rsi(s,n=14):
    d=s.diff();g=d.clip(lower=0);l=-d.clip(upper=0)
    ag=g.ewm(alpha=1/n,adjust=False,min_periods=n).mean();al=l.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=ag/al.where(al!=0,np.nan);o=100-(100/(1+rs));o[(al==0)&(ag>0)]=100;o[(ag==0)&(al>0)]=0;return o
def atr(d,n=14):
    pc=d.Close.shift(1);tr=pd.concat([(d.High-d.Low).abs(),(d.High-pc).abs(),(d.Low-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def adx(d,n=14):
    up=d.High.diff();dn=-d.Low.diff();p=up.where((up>dn)&(up>0),0);m=dn.where((dn>up)&(dn>0),0);a=atr(d,n)
    pdi=100*p.ewm(alpha=1/n,adjust=False).mean()/a;mdi=100*m.ewm(alpha=1/n,adjust=False).mean()/a
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan);return dx.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def zscore(s,n=20):m=s.rolling(n).mean();sd=s.rolling(n).std(ddof=0);return (s-m)/sd.replace(0,np.nan)
def pctlast(s,n=120):
    x=s.dropna()
    if len(x)<30:return np.nan
    w=x.iloc[-n:];return float((w<=w.iloc[-1]).mean()*100)
def compute(x):
    x=x.copy();x["EMA20"]=ema(x.Close,20);x["EMA50"]=ema(x.Close,50);x["EMA200"]=ema(x.Close,200)
    x["RSI5"]=rsi(x.Close,5);x["ATR14"]=atr(x);x["ADX14"]=adx(x);x["ZS20"]=zscore(x.Close,20)
    m=x.Close.rolling(20).mean();sd=x.Close.rolling(20).std(ddof=0);x["BBWIDTH"]=((m+2*sd)-(m-2*sd))/m.replace(0,np.nan)
    x["RELVOL20"]=x.Volume/x.Volume.rolling(20).mean().replace(0,np.nan);x["DOLLARVOL20"]=(x.Close*x.Volume).rolling(20).mean()
    rng=(x.High-x.Low).replace(0,np.nan);x["CLV"]=((x.Close-x.Low)/rng).clip(0,1)
    sign=np.sign(x.Close.diff()).fillna(0);x["SVP10"]=(sign*x.Volume).rolling(10).sum()/x.Volume.rolling(10).sum().replace(0,np.nan)
    x["GAP"]=x.Open/x.Close.shift(1)-1;x["HIGH20_PREV"]=x.High.shift(1).rolling(20).max();return x
