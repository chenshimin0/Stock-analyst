import sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from astock_data import *
code = "603296"
secid = f"1.{code}"
url = f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=13&klt=1&secid={secid}&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
req = urllib.request.Request(url, headers={"Referer": "https://quote.eastmoney.com/"})
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())
klines = data.get("data", {}).get("klines", [])
print(f"Got {len(klines)} klines")
for line in klines[-3:]:
    parts = line.split(",")
    print(f"  date={parts[0]} main_net[1]={parts[1]} pct[6]={parts[6]} close[11]={parts[11]} chg[12]={parts[12]}")
    print(f"  len={len(parts)}")
