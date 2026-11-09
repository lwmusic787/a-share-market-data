"""Daily A-share collection. Fail visibly; never invent missing quotes."""
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import akshare as ak
import pandas as pd

ROOT = Path("data")
ROOT.mkdir(exist_ok=True)
NOW = datetime.now(ZoneInfo("Asia/Shanghai"))
TODAY = NOW.strftime("%Y-%m-%d")
WATCH = {"002916":"深南电路","002463":"沪电股份","600183":"生益科技","002371":"北方华创","300476":"胜宏科技"}
INDEX = {"sh000001":"上证指数","sh000300":"沪深300","sz399006":"创业板指","sz399001":"深证成指"}
errors = []
success = {}

def save_csv(df, path, date_col=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path, dtype=str)
        df = pd.concat([old, df.astype(str)], ignore_index=True)
    if date_col and date_col in df:
        df = df.drop_duplicates(subset=[date_col], keep="last").sort_values(date_col)
    else:
        df = df.drop_duplicates()
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return len(df)

def attempt(name, fn):
    for i in range(3):
        try:
            return fn()
        except Exception as exc:
            if i == 2:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
            else:
                time.sleep(3 * (i + 1))
    return None

# Completed daily bars: public Eastmoney endpoints via AKShare.
for code, name in INDEX.items():
    df = attempt(code, lambda c=code: ak.stock_zh_index_daily_em(symbol=c))
    if df is not None and not df.empty:
        datecol = "date" if "date" in df.columns else "日期"
        df[datecol] = pd.to_datetime(df[datecol]).dt.strftime("%Y-%m-%d")
        df = df[df[datecol] <= TODAY]
        success[code] = save_csv(df, ROOT/"indices"/f"{code}.csv", datecol)

for code, name in WATCH.items():
    df = attempt(code, lambda c=code: ak.stock_zh_a_hist(symbol=c, period="daily", start_date="20240101", end_date=NOW.strftime("%Y%m%d"), adjust="qfq"))
    if df is not None and not df.empty:
        datecol = "日期"
        df[datecol] = pd.to_datetime(df[datecol]).dt.strftime("%Y-%m-%d")
        df = df[df[datecol] <= TODAY]
        success[code] = save_csv(df, ROOT/"stocks"/f"{code}.csv", datecol)

# Whole-market daily snapshot; availability varies by source.
spot = attempt("market_spot", ak.stock_zh_a_spot_em)
if spot is not None and not spot.empty:
    spot.to_csv(ROOT/"snapshots"/f"{TODAY}.csv", index=False, encoding="utf-8-sig") if (ROOT/"snapshots").mkdir(parents=True,exist_ok=True) is None else None
    success["market_spot"] = len(spot)

status = {"run_time_bjt":NOW.isoformat(),"source":"AKShare public data endpoints","success_rows":success,"errors":errors,"status":"ok" if not errors else "partial","note":"Snapshots may be intraday if manually triggered; scheduled run is after A-share close. Validate last row date before using."}
(ROOT/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(status,ensure_ascii=False,indent=2))
if not success:
    raise SystemExit("No market data retrieved")
