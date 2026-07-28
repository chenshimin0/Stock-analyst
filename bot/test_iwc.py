import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iwc_client import query, IwcLoginError, IwcQueryError
try:
    rows = query("603296", perpage=5)
    print(f"iwc OK: {len(rows)} rows")
    for r in rows[:3]:
        code = r.get("code", "")
        name = r.get("股票简称", "")
        print(f"  {code} {name}")
except IwcLoginError as e:
    print(f"LOGIN ERROR: {e}")
except IwcQueryError as e:
    print(f"QUERY ERROR: {e}")
