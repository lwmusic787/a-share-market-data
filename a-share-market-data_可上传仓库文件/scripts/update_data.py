"""Download A-share index OHLCV and publish validated CSV/JSON/indicators.

Run: python scripts/update_data.py
Data source: AKShare index_zh_a_hist (public third-party quote interface).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")
INDICES = {
    "sh000001": {"symbol": "000001", "name": "上证指数"},
    "sh000300": {"symbol": "000300", "name": "沪深300"},
    "sz399006": {"symbol": "399006", "name": "创业板指"},
    "sz399001": {"symbol": "399001", "name": "深证成指"},
}
COLUMNS = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount"}
MIN_ROWS = 300
KEEP_ROWS = 420  # > 250 for MA250 and rolling indicators


def fetch(symbol: str, start: str, end: str) -> pd.DataFrame:
    err = None
    for attempt in range(3):
        try:
            frame = ak.index_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end)
            if frame is None or frame.empty:
                raise ValueError("empty response")
            return frame
        except Exception as exc:
            err = exc
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"AKShare failed for {symbol}: {err}")


def validate(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{symbol}: missing fields {sorted(missing)}")
    df = frame.rename(columns=COLUMNS)[list(COLUMNS.values())].copy()
    df["date"] = pd.to_datetime(df["date"], errors="raise")
    for c in ["open", "high", "low", "close", "volume", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="raise")
    if df.isna().any().any():
        raise ValueError(f"{symbol}: null data")
    if df["date"].duplicated().any():
        raise ValueError(f"{symbol}: duplicate dates")
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < MIN_ROWS:
        raise ValueError(f"{symbol}: only {len(df)} rows, need {MIN_ROWS}")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{symbol}: non-positive prices")
    if (df["high"] < df[["open", "close", "low"]].max(axis=1)).any() or (df["low"] > df[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError(f"{symbol}: OHLC inconsistent")
    if (df[["volume", "amount"]] < 0).any().any():
        raise ValueError(f"{symbol}: negative volume/amount")
    today = datetime.now(TZ).date()
    last = df["date"].iloc[-1].date()
    if last > today:
        raise ValueError(f"{symbol}: future-dated data")
    if (today - last).days > 12:
        raise ValueError(f"{symbol}: data too stale ({last})")
    return df.tail(KEEP_ROWS).copy().reset_index(drop=True)


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    result = df.copy()
    for n in (5, 10, 20, 60, 120, 250):
        result[f"ma{n}"] = c.rolling(n, min_periods=n).mean()
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    result["macd_dif"] = ema12 - ema26
    result["macd_dea"] = result["macd_dif"].ewm(span=9, adjust=False).mean()
    result["macd_hist"] = 2 * (result["macd_dif"] - result["macd_dea"])
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's smoothing; RSI not reported before 14 price changes.
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result["rsi14"] = (100 - 100 / (1 + rs)).where(avg_loss.ne(0), 100.0)
    result.loc[avg_gain.eq(0) & avg_loss.eq(0), "rsi14"] = 50.0
    return result


def aggregate(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    x = df.set_index("date").resample(freq, label="right", closed="right").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), amount=("amount", "sum")
    ).dropna(subset=["close"])
    x.index.name = "period_end"
    return x.reset_index()


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def json_records(df: pd.DataFrame) -> list[dict]:
    x = df.copy()
    for col in x.select_dtypes(include=["datetime64[ns]"]).columns:
        x[col] = x[col].dt.strftime("%Y-%m-%d")
    return json.loads(x.to_json(orient="records", force_ascii=False, date_format="iso"))


def main() -> None:
    now = datetime.now(TZ)
    start = (now - timedelta(days=850)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    results = {}
    # Validate every symbol BEFORE writing, to avoid partially updated files on failure.
    for key, item in INDICES.items():
        raw = fetch(item["symbol"], start, end)
        df = validate(raw, key)
        results[key] = (item, df, indicators(df), aggregate(df, "W-FRI"), aggregate(df, "ME"))
    OUT.mkdir(exist_ok=True)
    manifest = {"source": "AKShare index_zh_a_hist / public upstream quotes", "timezone": "Asia/Shanghai", "retrieved_at": now.isoformat(), "status": "success", "indices": {}}
    for key, (item, df, tech, week, month) in results.items():
        df_csv = df.copy()
        df_csv["date"] = df_csv["date"].dt.strftime("%Y-%m-%d")
        df_csv.to_csv(OUT / f"{key}_daily.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
        tech_csv = tech.copy()
        tech_csv["date"] = tech_csv["date"].dt.strftime("%Y-%m-%d")
        tech_csv.to_csv(OUT / f"{key}_indicators.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
        week.to_csv(OUT / f"{key}_weekly.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
        month.to_csv(OUT / f"{key}_monthly.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
        write_json(OUT / f"{key}_daily.json", json_records(df))
        write_json(OUT / f"{key}_indicators.json", json_records(tech))
        manifest["indices"][key] = {"name": item["name"], "symbol": item["symbol"], "rows": len(df), "first_trade_date": df["date"].iloc[0].strftime("%Y-%m-%d"), "last_trade_date": df["date"].iloc[-1].strftime("%Y-%m-%d"), "latest_close": float(df["close"].iloc[-1]), "is_today": df["date"].iloc[-1].date() == now.date()}
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
