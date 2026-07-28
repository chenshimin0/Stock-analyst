import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from astock_data import get_fund_flow_recent
r = get_fund_flow_recent("603296", days=5)
print(f"Fund flow: {len(r)} days")
if r:
    for d in r[:3]:
        main = d["main_net"] / 1e8
        print(f"  {d['date']} main_net={main:.2f}yi")
else:
    print("  EMPTY")
