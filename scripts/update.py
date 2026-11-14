"""Incremental A-share archive. No synthetic prices; failures remain visible."""
import json, os, time
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
BATCH_SIZE = max(1, int(os.getenv("BACKFILL_BATCH_SIZE", "180")))
START = os.getenv("BACKFILL_START", "20240101")
errors, success = [], {}
rate_limited = False

def is_rate_limit(exc):
    return "Push2RateLimitError" in str(exc) or "限流" in str(exc)

def attempt(label, fn):
    global rate_limited
    for i in range(2):
        try:
            result = fn()
            if result is None or result.empty:
                raise ValueError("empty response")
            return result
        except Exception as e:
            if is_rate_limit(e):
                rate_limited = True
                errors.append(f"{label}: rate limited: {e}")
                return None
            if i == 1:
                errors.append(f"{label}: {type(e).__name__}: {e}")
            else:
                time.sleep(5*(i+1))
    return None

def save(df, path, datecol):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        prior = pd.read_csv(path, dtype=str)
        df = pd.concat([prior, df.astype(str)], ignore_index=True)
    df[datecol] = pd.to_datetime(df[datecol], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=[datecol])
    df = df[df[datecol] <= TODAY].drop_duplicates(subset=[datecol], keep="last").sort_values(datecol)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return len(df), (df[datecol].iloc[-1] if len(df) else None)

for code in INDEX:
    df = None if rate_limited else attempt(code, lambda c=code: ak.stock_zh_index_daily_em(symbol=c))
    if df is None:
        df = attempt(code+"_sina", lambda c=code: ak.stock_zh_index_daily(symbol=c))
    if df is not None:
        col = "date" if "date" in df.columns else "日期"
        count, latest = save(df, ROOT/"indices"/f"{code}.csv", col)
        success[code] = {"rows":count,"latest":latest}

spot = None if rate_limited else attempt("market_spot", ak.stock_zh_a_spot_em)
if spot is None:
    spot = attempt("market_spot_sina", ak.stock_zh_a_spot)
universe_path = ROOT/"universe.csv"
if spot is not None:
    (ROOT/"snapshots").mkdir(parents=True, exist_ok=True)
    spot.to_csv(ROOT/"snapshots"/f"{TODAY}.csv", index=False, encoding="utf-8-sig")
    success["market_spot"] = {"rows":len(spot),"date":TODAY}
    code_column = "代码" if "代码" in spot.columns else "code"
    codes = spot[code_column].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True).str.zfill(6)
    names = spot["名称"].astype(str) if "名称" in spot.columns else (spot["name"].astype(str) if "name" in spot.columns else codes)
    universe = pd.DataFrame({"code":codes, "name":names})
    universe = universe[universe.code.str.fullmatch(r"[0-9]{6}")].drop_duplicates("code").sort_values("code")
    universe.to_csv(universe_path, index=False, encoding="utf-8-sig")
elif universe_path.exists():
    universe = pd.read_csv(universe_path, dtype=str)
else:
    universe = pd.DataFrame(columns=["code","name"])

codes = sorted(set(universe["code"].astype(str).tolist()) | set(WATCH))
cursor_file = ROOT/"backfill_cursor.json"
cursor = json.loads(cursor_file.read_text(encoding="utf-8")) if cursor_file.exists() else {}
offset = int(cursor.get("offset",0)) % max(len(codes),1)
batch = (codes[offset:offset+BATCH_SIZE] + codes[:max(0,offset+BATCH_SIZE-len(codes))]) if codes else []
batch = list(dict.fromkeys(batch + list(WATCH)))
for code in batch:
    path = ROOT/"stocks"/f"{code}.csv"
    # Preserve a long historical window; refresh the most recent dates each run.
    start = START
    if path.exists():
        try:
            prev = pd.read_csv(path, usecols=["日期"], dtype=str)
            if len(prev):
                recent = (pd.to_datetime(prev["日期"].max()) - pd.Timedelta(days=30)).strftime("%Y%m%d")
                start = max(START, recent)
        except Exception:
            pass
    df = None if rate_limited else attempt(code, lambda c=code,s=start: ak.stock_zh_a_hist(symbol=c,period="daily",start_date=s,end_date=NOW.strftime("%Y%m%d"),adjust="qfq"))
    if df is None:
        prefix = "sh" if code.startswith(("6","9")) else "bj" if code.startswith(("4","8")) else "sz"
        df = attempt(code+"_sina", lambda p=prefix,c=code,s=start: ak.stock_zh_a_daily(symbol=p+c,start_date=s,end_date=NOW.strftime("%Y%m%d"),adjust="qfq"))
        if df is not None:
            df = df.rename(columns={"date":"日期","open":"开盘","high":"最高","low":"最低","close":"收盘","volume":"成交量"})
    if df is not None:
        count, latest = save(df, path, "日期")
        success[code] = {"rows":count,"latest":latest}
cursor_file.write_text(json.dumps({"offset":(offset+BATCH_SIZE)%max(len(codes),1),"universe_size":len(codes),"batch_size":BATCH_SIZE,"updated_bjt":NOW.isoformat()},ensure_ascii=False,indent=2),encoding="utf-8")
stock_dir = ROOT/"stocks"
stored = len(list(stock_dir.glob("*.csv"))) if stock_dir.exists() else 0
status = {"run_time_bjt":NOW.isoformat(),"source":"AKShare public endpoints","status":"ok" if not errors else "partial","errors":errors,"success_rows":success,"coverage":{"universe":len(codes),"stocks_with_files":stored,"batch_attempted":len(batch),"all_stocks_complete":False},"note":"Completeness requires per-symbol trading-calendar/date validation; snapshot is not an official exchange close."}
(ROOT/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(status,ensure_ascii=False,indent=2))
if not success:
    raise SystemExit("No data retrieved; existing files preserved")
