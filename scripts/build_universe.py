import re,requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from common import DATA,CONFIG,load_json,save_json,now_iso
H={"User-Agent":"Mozilla/5.0 Chrome/151 Safari/537.36"}
START=["https://swyftx.com/sitemap.xml","https://swyftx.com/au/sitemap.xml"]
CG="https://api.coingecko.com/api/v3/coins/list"
ALIASES={"xrp":"ripple","avalanche":"avalanche-2","polygon":"matic-network","near-protocol":"near"}
def get(u):
    r=requests.get(u,headers=H,timeout=40);r.raise_for_status();return r.text
def discover():
    seen=set();q=list(START);urls=set()
    while q:
        u=q.pop(0)
        if u in seen:continue
        seen.add(u)
        try:s=BeautifulSoup(get(u),"xml")
        except:continue
        for loc in [x.get_text(strip=True) for x in s.find_all("loc")]:
            if "/au/buy/" in loc:urls.add(loc.rstrip("/"))
            elif loc.endswith(".xml") and "sitemap" in loc.lower() and loc not in seen:q.append(loc)
    return sorted(urls)
def slug(u):
    p=urlparse(u).path.strip("/").split("/")
    try:return p[p.index("buy")+1].lower()
    except:return None
def norm(s):return re.sub(r"[^a-z0-9]","",str(s or "").lower())
def main():
    old=load_json(DATA/"universe.json",[])
    try:
        coins=requests.get(CG,headers=H,timeout=60).json()
        byid={str(c.get("id","")).lower():c for c in coins}
        byname={}
        for c in coins:byname.setdefault(norm(c.get("name","")),[]).append(c)
        rows={}
        for u in discover():
            s=slug(u)
            if not s:continue
            c=byid.get(s) or byid.get(ALIASES.get(s,""))
            if not c:
                cand=byname.get(norm(s.replace("-"," ")),[])
                c=cand[0] if len(cand)==1 else None
            if not c:continue
            sym=str(c.get("symbol","")).upper()
            if not sym or sym in CONFIG["exclude_symbols"]:continue
            key=c.get("id") or sym
            rows[key]={"symbol":sym,"name":c.get("name"),"coingecko_id":c.get("id"),"binance_symbol":sym+"USDT","swyftx_url":u,"source":"Swyftx listing + CoinGecko map","discovered_at":now_iso()}
        universe=sorted(rows.values(),key=lambda x:(x["symbol"],x["name"]))
        if len(universe)<100:
            if len(old)>=100:
                print("Universe refresh failed; retained cached universe",len(old));return
            raise RuntimeError(f"Only {len(universe)} assets resolved")
        save_json(DATA/"universe.json",universe)
        print("Swyftx universe:",len(universe))
    except Exception as e:
        if len(old)>=100:
            print("Universe refresh failed; retained cached universe",len(old),e);return
        raise
if __name__=="__main__":main()
