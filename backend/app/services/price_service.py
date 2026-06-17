import time
import asyncio
from typing import Optional
import httpx

from app.config import CACHE_TTL_SECONDS
from app.utils import parse_tencent_realtime, get_tencent_code

TENCENT_URL = "http://qt.gtimg.cn/q={codes}"
_cache: dict = {}
_batch_cache: dict = {}


class PriceService:
    @staticmethod
    async def get_realtime_price(stock_code: str) -> Optional[dict]:
        cache_key = f"rt_{stock_code}"
        now = time.time()
        if cache_key in _cache and now - _cache[cache_key]["ts"] < CACHE_TTL_SECONDS:
            return _cache[cache_key]["data"]

        tc = get_tencent_code(stock_code)
        url = TENCENT_URL.format(codes=tc)

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code != 200:
                    return None
                raw = resp.content.decode("gbk", errors="replace")
                data = parse_tencent_realtime(stock_code, raw)
                if data:
                    _cache[cache_key] = {"data": data, "ts": now}
                return data
        except Exception:
            return None

    @staticmethod
    async def get_realtime_prices_batch(codes: list[str]) -> list[dict]:
        if not codes:
            return []

        cache_key = ",".join(sorted(codes))
        now = time.time()
        if cache_key in _batch_cache and now - _batch_cache[cache_key]["ts"] < CACHE_TTL_SECONDS:
            return _batch_cache[cache_key]["data"]

        # Check individual caches first
        results = []
        uncached = []
        for c in codes:
            if f"rt_{c}" in _cache and now - _cache[f"rt_{c}"]["ts"] < CACHE_TTL_SECONDS:
                results.append(_cache[f"rt_{c}"]["data"])
            else:
                uncached.append(c)

        if not uncached:
            return results

        # Batch request for uncached codes
        tc_list = [get_tencent_code(c) for c in uncached]
        url = TENCENT_URL.format(codes=",".join(tc_list))

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    raw = resp.content.decode("gbk", errors="replace")
                    # Parse each line and match by actual code from response
                    for line in raw.strip().split("\n"):
                        line = line.strip()
                        if not line or "=" not in line or '"' not in line:
                            continue
                        data = parse_tencent_realtime("", line)
                        if data and data.get("price", 0) > 0:
                            code = data["code"]
                            results.append(data)
                            _cache[f"rt_{code}"] = {"data": data, "ts": now}
        except Exception:
            pass

        # Parallel fallback for codes that still don't have data
        still_missing = [c for c in uncached if f"rt_{c}" not in _cache or now - _cache[f"rt_{c}"]["ts"] >= CACHE_TTL_SECONDS]
        if still_missing:
            tasks = [PriceService._fetch_single(c) for c in still_missing]
            individual_results = await asyncio.gather(*tasks, return_exceptions=True)
            for data in individual_results:
                if data and not isinstance(data, Exception) and data.get("price", 0) > 0:
                    results.append(data)

        _batch_cache[cache_key] = {"data": results, "ts": now}
        return results

    @staticmethod
    async def _fetch_single(stock_code: str) -> Optional[dict]:
        now = time.time()
        tc = get_tencent_code(stock_code)
        url = TENCENT_URL.format(codes=tc)
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code != 200:
                    return None
                raw = resp.content.decode("gbk", errors="replace")
                data = parse_tencent_realtime(stock_code, raw)
                if data:
                    _cache[f"rt_{stock_code}"] = {"data": data, "ts": now}
                return data
        except Exception:
            return None

    @staticmethod
    async def _fetch_kline_data(stock_code: str) -> list[dict]:
        """Fetch raw 10jqka daily K-line data (前复权). Returns list of {date, close, ...}."""
        import re
        import json

        url = f"http://d.10jqka.com.cn/v2/line/hs_{stock_code}/01/last.js"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://stockpage.10jqka.com.cn/",
                })
                if resp.status_code != 200:
                    return []
                text = resp.text
                m = re.search(r"\((\{.*\})\)", text, re.DOTALL)
                if not m:
                    return []
                data = json.loads(m.group(1))
                data_str = data.get("data", "")
                if not data_str:
                    return []

                result = []
                for line in data_str.split(";"):
                    parts = line.split(",")
                    if len(parts) < 5:
                        continue
                    result.append({
                        "date": parts[0],
                        "open": float(parts[1]),
                        "high": float(parts[2]),
                        "low": float(parts[3]),
                        "close": float(parts[4]),
                    })
                return result
        except Exception:
            return []

    @staticmethod
    def _lookup_kline_close(kline_data: list[dict], target_date: str) -> Optional[float]:
        """Look up close price in K-line data for a date (YYYYMMDD format). Falls back to nearest prior date."""
        closest = None
        for bar in kline_data:
            if bar["date"] == target_date:
                return bar["close"]
            if bar["date"] < target_date:
                closest = bar["close"]
        return closest

    @staticmethod
    async def get_adjusted_close(stock_code: str, target_date: str) -> Optional[float]:
        """Get 前复权 closing price for a date using 10jqka daily K-line."""
        kline = await PriceService._fetch_kline_data(stock_code)
        if not kline:
            return None
        return PriceService._lookup_kline_close(kline, target_date.replace("-", ""))

    @staticmethod
    async def get_historical_price(stock_code: str, target_date: str) -> Optional[float]:
        """Fetch closing price on target_date from Tencent Finance.

        target_date format: YYYYMMDD (or YYYY-MM-DD).
        Uses Tencent's daily K-line endpoint which has worked reliably
        from this server (akshare / EastMoney are blocked).
        """
        import gzip
        import json
        import urllib.request
        from datetime import datetime, timedelta
        try:
            target_str = target_date.replace("-", "")
            target_dt = datetime.strptime(target_str, "%Y%m%d").date()
        except ValueError:
            return None
        try:
            # Tencent daily K-line URL: 前复权
            prefix = "sh" if stock_code.startswith(("6", "9")) else "sz"
            start = (target_dt - timedelta(days=15)).strftime("%Y-%m-%d")
            end = (target_dt + timedelta(days=2)).strftime("%Y-%m-%d")
            url = (
                f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
                f"param={prefix}{stock_code},day,{start},{end},60,qfq"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            data = json.loads(raw)
            key = f"{prefix}{stock_code}"
            klines = (
                data.get("data", {}).get(key, {}).get("qfqday")
                or data.get("data", {}).get(key, {}).get("day")
                or []
            )
            target_str_dash = target_dt.strftime("%Y-%m-%d")
            closest = None
            for bar in klines:
                if len(bar) < 3:
                    continue
                bar_date = str(bar[0])
                if len(bar_date) >= 10:
                    bar_date = bar_date[:10]
                try:
                    bar_price = float(bar[2])
                except (ValueError, TypeError):
                    continue
                if bar_date == target_str_dash:
                    return bar_price
                # Fallback: nearest prior trading day
                if bar_date < target_str_dash:
                    closest = bar_price
            return closest
        except Exception:
            return None
