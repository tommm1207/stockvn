"""
data_fetcher.py – Nguồn dữ liệu:
  PRIMARY  : yfinance (Yahoo Finance) – lịch sử daily, hoạt động 24/7
  INTRADAY : DNSE entrade API – nến trong ngày (1 phút), giờ giao dịch
  INDEX    : yfinance ^VNINDEX, ^HNX, ^UPCOM

Data Quality:
  - Mỗi response có metadata: data_source, cached, fetched_at, warnings
  - Cache TTL cấu hình qua env
  - Fallback graceful: không trả 500 cho lỗi nguồn dữ liệu
"""

import asyncio
import copy
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)



DNSE_CHART = "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
DNSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/120",
    "Origin": "https://banggia.dnse.com.vn",
    "Referer": "https://banggia.dnse.com.vn/",
}

# ─── Configurable TTL (seconds) ──────────────────────────────────────────────
HISTORICAL_CACHE_TTL = int(os.getenv("HISTORICAL_CACHE_TTL_SECONDS", "300"))
TOP_MOVERS_CACHE_TTL = int(os.getenv("TOP_MOVERS_CACHE_TTL_SECONDS", "120"))
MARKET_OVERVIEW_CACHE_TTL = int(os.getenv("MARKET_OVERVIEW_CACHE_TTL_SECONDS", "180"))

_historical_cache = {}
_top_movers_cache = {}
_market_overview_cache = {}
_cache_lock = asyncio.Lock()


# ─── Cache helpers ────────────────────────────────────────────────────────────

async def _get_cache(cache: dict, key):
    async with _cache_lock:
        item = cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            cache.pop(key, None)
            return None
        return copy.deepcopy(value)


async def _set_cache(cache: dict, key, value, ttl: int):
    async with _cache_lock:
        cache[key] = (time.time() + ttl, copy.deepcopy(value))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Data Result Wrapper ─────────────────────────────────────────────────────

def _make_result(data, source: str = "unknown", cached: bool = False,
                 warnings: list = None, error: str = None) -> dict:
    """Wrap raw data with quality metadata."""
    return {
        "data": data,
        "data_source": source,
        "cached": cached,
        "fetched_at": _now_iso(),
        "warnings": warnings or [],
        "error": error,
    }


# Map mã VN → Yahoo Finance ticker

INDEX_MAP = {
    "VNINDEX": "VNINDEX",
    "HNX": "HNX",
    "UPCOM": "UPCOM",
}

DNSE_INDEX = "https://services.entrade.com.vn/chart-api/v2/ohlcs/index"

async def _fetch_dnse_index(index_symbol: str) -> dict:
    """Lấy chỉ số từ DNSE (daily hoặc 1min intraday)"""
    now = int(time.time())
    # Try daily bars for last 5 trading days
    params_d = {"from": now - 10*86400, "to": now, "symbol": index_symbol, "resolution": "D"}
    params_1 = {"from": now - 86400, "to": now, "symbol": index_symbol, "resolution": "1"}
    async with httpx.AsyncClient(timeout=10) as c:
        for params in [params_d, params_1]:
            try:
                r = await c.get(DNSE_INDEX, params=params, headers=DNSE_HEADERS)
                d = r.json()
                closes = d.get("c") or []
                times = d.get("t") or []
                if len(closes) >= 2:
                    val = float(closes[-1])
                    prev = float(closes[-2])
                    change = val - prev
                    change_pct = (change / prev * 100) if prev else 0
                    return {
                        "value": round(val, 2),
                        "change": round(change, 2),
                        "change_pct": round(change_pct, 2),
                        "date": datetime.fromtimestamp(times[-1]).strftime("%Y-%m-%d") if times else "",
                    }
            except Exception as e:
                logger.warning(f"DNSE index {index_symbol} error: {e}")
    return {"value": 0, "change": 0, "change_pct": 0}

# ─── Historical Daily Data ────────────────────────────────────────

async def get_historical_data(symbol: str, days: int = 300) -> list:
    """Lấy dữ liệu OHLCV lịch sử từ DNSE và VNDirect"""
    symbol = symbol.upper()
    cache_key = f"hist_{symbol}_{days}"
    cached = await _get_cache(_historical_cache, cache_key)
    if cached is not None:
        return cached

    url = "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
    end_time = int(time.time())
    start_time = end_time - ((days + 10) * 86400)
    params = {"symbol": symbol, "resolution": "1D", "from": start_time, "to": end_time}
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params, headers=DNSE_HEADERS)
            data = r.json()
            if "t" not in data or not data["t"]:
                return []
                
            results = []
            for i in range(len(data["t"])):
                dt_str = datetime.fromtimestamp(data["t"][i]).strftime("%Y-%m-%d")
                results.append({"date": dt_str, "open": float(data["o"][i]), "high": float(data["h"][i]), "low": float(data["l"][i]), "close": float(data["c"][i]), "volume": int(data["v"][i])})
            
            # Trả về đúng số lượng nến yêu cầu
            results = results[-days:] if len(results) > days else results
            
            # Cập nhật thêm dữ liệu Khối ngoại từ VNDirect cho các nến
            try:
                start_date_str = results[0]["date"]
                vnd_url = f"https://finfo-api.vndirect.com.vn/v4/stock_prices?sort=date&q=code:{symbol}~date:gte:{start_date_str}"
                vnd_r = await client.get(vnd_url, timeout=2.0)
                vnd_data = vnd_r.json().get("data", [])
                
                # Map by date
                vnd_map = {item["date"]: item for item in vnd_data}
                
                for r in results:
                    vnd_info = vnd_map.get(r["date"])
                    if vnd_info:
                        f_buy = vnd_info.get("fBuyVol", 0)
                        f_sell = vnd_info.get("fSellVol", 0)
                        r["foreign_buy"] = f_buy
                        r["foreign_sell"] = f_sell
                        r["foreign_net"] = f_buy - f_sell
            except Exception:
                pass

            await _set_cache(_historical_cache, cache_key, results, HISTORICAL_CACHE_TTL)
            return results
    except Exception as e:
        logger.error(f"Lỗi lấy dữ liệu lịch sử cho {symbol}: {e}")
        return []

# ─── Intraday Data (DNSE) ────────────────────────────────────────────────────

SECTOR_VI = {
    "Real Estate": "Bất Động Sản",
    "Financial Services": "Tài Chính",
    "Technology": "Công Nghệ Thông Tin",
    "Healthcare": "Y Tế",
    "Consumer Defensive": "Hàng Tiêu Dùng Thiết Yếu",
    "Consumer Cyclical": "Hàng Tiêu Dùng K.Thiết Yếu",
    "Industrials": "Công Nghiệp",
    "Utilities": "Điện, Nước & Tiện Ích",
    "Energy": "Dầu Khí",
    "Basic Materials": "Tài Nguyên Cơ Bản",
    "Communication Services": "Viễn Thông",
}

INDUSTRY_VI = {
    # Bất Động Sản
    "Real Estate Services": "Dịch Vụ Bất Động Sản",
    "Real Estate—Development": "Phát Triển Bất Động Sản",
    "Real Estate - Development": "Phát Triển Bất Động Sản",
    "Real Estate—Diversified": "Bất Động Sản Tổng Hợp",
    # Tài Chính (Ngân Hàng, Chứng Khoán, Bảo Hiểm)
    "Banks - Regional": "Ngân Hàng",
    "Banks—Regional": "Ngân Hàng",
    "Banks - Diversified": "Ngân Hàng",
    "Banks—Diversified": "Ngân Hàng",
    "Asset Management": "Chứng Khoán & Quản Lý Quỹ",
    "Capital Markets": "Thị Trường Vốn",
    "Credit Services": "Dịch Vụ Tín Dụng",
    "Insurance - Life": "Bảo Hiểm",
    "Insurance—Life": "Bảo Hiểm",
    "Insurance - Property & Casualty": "Bảo Hiểm",
    "Insurance—Property & Casualty": "Bảo Hiểm",
    "Insurance - Reinsurance": "Bảo Hiểm",
    "Insurance - Diversified": "Bảo Hiểm Tổng Hợp",
    "Financial Data & Stock Exchanges": "Sàn Giao Dịch & Dữ Liệu",
    # Viễn Thông & Công Nghệ
    "Telecom Services": "Viễn Thông",
    "Software - Infrastructure": "Phần Mềm",
    "Software—Infrastructure": "Phần Mềm",
    "Software - Application": "Phần Mềm Ứng Dụng",
    "Software—Application": "Phần Mềm Ứng Dụng",
    "Information Technology Services": "Dịch Vụ CNTT",
    "Computer Hardware": "Phần Cứng Máy Tính",
    "Communication Equipment": "Thiết Bị Viễn Thông",
    "Electronic Components": "Linh Kiện Điện Tử",
    # Công Nghiệp, Vận tải & Xây Dựng
    "Conglomerates": "Tập Đoàn Đa Ngành",
    "Building Products & Equipment": "Vật Liệu Xây Dựng",
    "Engineering & Construction": "Xây Dựng",
    "Infrastructure Operations": "Khai Thác Hạ Tầng",
    "Aerospace & Defense": "Hàng Không & Quốc Phòng",
    "Airlines": "Hàng Không",
    "Airports & Air Services": "Dịch Vụ Sân Bay",
    "Marine Shipping": "Vận Tải Biển",
    "Trucking": "Vận Tải Đường Bộ",
    "Integrated Freight & Logistics": "Logistics & Kho Bãi",
    "Industrial Distribution": "Phân Phối Công Nghiệp",
    "Electrical Equipment & Parts": "Thiết Bị Điện",
    "Metal Fabrication": "Gia Công Kim Loại",
    "Specialty Industrial Machinery": "Máy Móc Công Nghiệp",
    # Tiêu dùng & Thực phẩm
    "Packaged Foods": "Thực Phẩm",
    "Farm Products": "Nông Lâm Thủy Sản",
    "Beverages—Non-Alcoholic": "Đồ Uống Không Cồn",
    "Beverages - Non-Alcoholic": "Đồ Uống Không Cồn",
    "Beverages—Brewers": "Bia & Đồ Uống",
    "Beverages - Brewers": "Bia & Đồ Uống",
    "Food Distribution": "Phân Phối Thực Phẩm",
    "Grocery Stores": "Bán Lẻ Thực Phẩm",
    "Discount Stores": "Bán Lẻ Đa Năng",
    "Apparel Manufacturing": "Dệt May",
    "Footwear & Accessories": "Giày Dép & Phụ Kiện",
    "Textile Manufacturing": "Dệt May",
    "Personal Services": "Dịch Vụ Cá Nhân",
    "Restaurants": "Nhà Hàng & Ăn Uống",
    "Travel Services": "Du Lịch & Giải Trí",
    "Lodging": "Khách Sạn & Lưu Trú",
    # Vật liệu, Hóa chất, Khai khoáng
    "Steel": "Thép",
    "Aluminum": "Nhôm",
    "Other Industrial Metals & Mining": "Khai Khoáng & Luyện Kim",
    "Chemicals": "Hóa Chất",
    "Specialty Chemicals": "Hóa Chất Chuyên Dụng",
    "Agricultural Inputs": "Phân Bón & Nông Dược",
    "Paper & Paper Products": "Sản Xuất Giấy",
    "Lumber & Wood Production": "Sản Xuất Gỗ",
    "Packaging & Containers": "Bao Bì",
    # Năng lượng & Tiện ích
    "Oil & Gas Integrated": "Dầu Khí",
    "Oil & Gas E&P": "Thăm Dò & Khai Thác Dầu Khí",
    "Oil & Gas Refining & Marketing": "Lọc Hóa Dầu",
    "Utilities - Regulated Electric": "Sản Xuất & Phân Phối Điện",
    "Utilities—Regulated Electric": "Sản Xuất & Phân Phối Điện",
    "Utilities - Regulated Water": "Cấp Nước",
    "Utilities—Regulated Water": "Cấp Nước",
    "Utilities - Renewable": "Năng Lượng Tái Tạo",
    # Khác
    "Auto Manufacturers": "Ô tô & Phụ Tùng",
    "Auto Parts": "Ô tô & Phụ Tùng",
    "Drug Manufacturers - General": "Dược Phẩm",
    "Drug Manufacturers—General": "Dược Phẩm",
    "Medical Devices": "Thiết Bị Y Tế",
}

COMPANY_NAMES_VI = {
    "VNM": "CTCP Sữa Việt Nam (Vinamilk)",
    "VIC": "Tập đoàn Vingroup",
    "VHM": "CTCP Vinhomes",
    "VRE": "CTCP Vincom Retail",
    "HPG": "CTCP Tập đoàn Hòa Phát",
    "MSN": "CTCP Tập đoàn Masan",
    "VCB": "Ngân hàng TMCP Ngoại thương VN (Vietcombank)",
    "BID": "Ngân hàng TMCP Đầu tư và Phát triển VN (BIDV)",
    "CTG": "Ngân hàng TMCP Công Thương VN (VietinBank)",
    "TCB": "Ngân hàng TMCP Kỹ Thương VN (Techcombank)",
    "MBB": "Ngân hàng TMCP Quân Đội (MB)",
    "VPB": "Ngân hàng TMCP Việt Nam Thịnh Vượng (VPBank)",
    "ACB": "Ngân hàng TMCP Á Châu (ACB)",
    "STB": "Ngân hàng TMCP Sài Gòn Thương Tín (Sacombank)",
    "HDB": "Ngân hàng TMCP Phát triển TP.HCM (HDBank)",
    "VIB": "Ngân hàng TMCP Quốc tế VN (VIB)",
    "TPB": "Ngân hàng TMCP Tiên Phong (TPBank)",
    "SHB": "Ngân hàng TMCP Sài Gòn - Hà Nội (SHB)",
    "SSB": "Ngân hàng TMCP Đông Nam Á (SeABank)",
    "EIB": "Ngân hàng TMCP Xuất Nhập khẩu VN (Eximbank)",
    "LPB": "Ngân hàng TMCP Lộc Phát VN (LPBank)",
    "SSI": "CTCP Chứng khoán SSI",
    "VND": "CTCP Chứng khoán VNDIRECT",
    "VCI": "CTCP Chứng khoán Vietcap",
    "HCM": "CTCP Chứng khoán TP.HCM (HSC)",
    "FPT": "CTCP FPT",
    "MWG": "CTCP Đầu tư Thế Giới Di Động",
    "PNJ": "CTCP Vàng bạc Đá quý Phú Nhuận",
    "REE": "CTCP Cơ Điện Lạnh",
    "DGC": "CTCP Tập đoàn Hóa chất Đức Giang",
    "DCM": "CTCP Phân bón Dầu khí Cà Mau",
    "DPM": "Tổng CTCP Phân bón và Hóa chất Dầu khí",
    "NLG": "CTCP Đầu tư Nam Long",
    "KDH": "CTCP Đầu tư và Kinh doanh Nhà Khang Điền",
    "NVL": "CTCP Tập đoàn Đầu tư Địa ốc No Va (Novaland)",
    "PDR": "CTCP Phát triển Bất động sản Phát Đạt",
    "DIG": "Tổng CTCP Đầu tư Phát triển Xây dựng (DIC Corp)",
    "DXG": "CTCP Tập đoàn Đất Xanh",
    "VJC": "CTCP Hàng không Vietjet",
    "HVN": "Tổng Công ty Hàng không VN (Vietnam Airlines)",
    "GAS": "Tổng Công ty Khí VN (PV GAS)",
    "PLX": "Tập đoàn Xăng dầu VN (Petrolimex)",
    "POW": "Tổng Công ty Điện lực Dầu khí VN",
    "SAB": "Tổng CTCP Bia - Rượu - Nước giải khát Sài Gòn (Sabeco)",
    "GVR": "Tập đoàn Công nghiệp Cao su VN",
    "BCM": "Tổng Công ty Đầu tư và Phát triển Công nghiệp (Becamex IDC)",
}

def translate_company_name(symbol: str, info: dict) -> str:
    sym = symbol.upper()
    if sym in COMPANY_NAMES_VI:
        return COMPANY_NAMES_VI[sym]
    name = info.get("longName") or info.get("shortName") or symbol
    
    # Generic replacement
    reps = {
        "Joint Stock Commercial Bank for Foreign Trade of Vietnam": "Ngân hàng TMCP Ngoại thương VN",
        "Vietnam Joint Stock Commercial Bank for Industry and Trade": "Ngân hàng TMCP Công Thương VN",
        "Joint Stock Commercial Bank": "Ngân hàng TMCP",
        "Commercial Joint Stock Bank": "Ngân hàng TMCP",
        "Joint Stock Bank": "Ngân hàng TMCP",
        "Joint Stock Company": "CTCP",
        "Joint-Stock Company": "CTCP",
        "Corporation": "Tổng Công ty/Tập đoàn",
        "Group": "Tập đoàn",
        "Securities": "Chứng khoán",
        "Holdings": "Tập đoàn",
        "Vietnam": "VN",
    }
    for k, v in reps.items():
        name = name.replace(k, v)
    return name

def _fetch_fundamentals_sync(symbol: str) -> dict:
    fallback_name = get_company_name_sync(symbol)
    market_cap, pe, pb, eps, roe = 0, 0, 0, 0, 0
    try:
        import requests
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"https://finfo-api.vndirect.com.vn/v4/ratios?q=code:{symbol}")
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                item = data[0]
                pe = item.get("pe", 0)
                pb = item.get("pb", 0)
                eps = item.get("eps", 0)
                roe = item.get("roe", 0) / 100 if item.get("roe") else 0
                
        r2 = requests.get(f"https://services.entrade.com.vn/chart-api/chart/symbol?symbol={symbol}", timeout=5)
        if r2.status_code == 200:
            mc = r2.json().get("marketCap", 0)
            if mc: market_cap = mc
    except Exception as e:
        logger.warning(f"Error fetching fundamental stats for {symbol}: {e}")

    return {
        "name": fallback_name,
        "sector": "Tài chính/BĐS/SX",
        "industry": "Không xác định",
        "market_cap": market_cap,
        "shares_outstanding": 0,
        "pe_ratio": pe,
        "pb_ratio": pb,
        "eps": eps,
        "roe": roe,
        "beta": 1.0,
        "dividend_yield": 0
    }


async def get_fundamentals(symbol: str) -> dict:
    """Async wrapper – yfinance là sync nên chạy trong threadpool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_fundamentals_sync, symbol)

def _fetch_deep_fundamentals_sync(symbol: str) -> dict:
    income_stmt = {}
    balance_sheet = {}
    try:
        import requests
        url = f"https://finfo-api.vndirect.com.vn/v4/financial_statements?q=code:{symbol}~reportType:QUARTER&sort=-fiscalDate&size=4"
        async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(url)
        if r.status_code == 200:
            data = r.json().get("data", [])
            for item in data:
                q = f"Q{item.get('fiscalQuarter')} {item.get('fiscalYear')}"
                if "netRevenue" in item:
                    income_stmt[q] = {
                        "Revenue": item.get("netRevenue", 0),
                        "Net Income": item.get("netIncome", 0)
                    }
                if "totalAssets" in item:
                    balance_sheet[q] = {
                        "Total Assets": item.get("totalAssets", 0),
                        "Total Debt": item.get("shortTermDebt", 0) + item.get("longTermDebt", 0),
                        "Total Equity": item.get("equity", 0)
                    }
    except Exception as e:
        logger.warning(f"Error fetching deep fundamentals: {e}")

    return {
        "income_statement": income_stmt,
        "balance_sheet": balance_sheet,
        "cash_flow": {}
    }

async def get_deep_fundamentals(symbol: str) -> dict:
    """Async wrapper cho deep fundamentals."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_deep_fundamentals_sync, symbol)



async def get_intraday_chart(symbol: str, resolution: str = "15", hours: int = 72) -> list:
    """Lấy nến intraday từ DNSE với resolution tùy chọn (1, 5, 15, 30, 60 phút)."""
    to_ts = int(time.time())
    from_ts = to_ts - hours * 3600
    params = {"from": from_ts, "to": to_ts, "symbol": symbol.upper(), "resolution": str(resolution)}
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get(DNSE_CHART, params=params, headers=DNSE_HEADERS)
            r.raise_for_status()
            d = r.json()
            times = d.get("t") or []
            opens = d.get("o") or []
            highs = d.get("h") or []
            lows = d.get("l") or []
            closes = d.get("c") or []
            vols = d.get("v") or []
            result = []
            for i, t in enumerate(times):
                result.append({
                    "date": int(t),  # unix seconds (lightweight-charts hỗ trợ)
                    "time_str": datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M"),
                    "open": round(float(opens[i]) * 1000, 0) if i < len(opens) else 0,
                    "high": round(float(highs[i]) * 1000, 0) if i < len(highs) else 0,
                    "low": round(float(lows[i]) * 1000, 0) if i < len(lows) else 0,
                    "close": round(float(closes[i]) * 1000, 0) if i < len(closes) else 0,
                    "volume": int(vols[i]) if i < len(vols) else 0,
                })
            return result
        except Exception as e:
            logger.error(f"DNSE intraday error for {symbol} (res={resolution}): {e}")
            return []


async def get_intraday_data(symbol: str, minutes: int = 480) -> list:
    """Lấy dữ liệu intraday từ DNSE (1 phút) – chỉ có trong giờ giao dịch"""
    to_ts = int(time.time())
    from_ts = to_ts - minutes * 60
    url = DNSE_CHART
    params = {"from": from_ts, "to": to_ts, "symbol": symbol.upper(), "resolution": "1"}
    async with httpx.AsyncClient(timeout=10) as c:
        try:
            r = await c.get(url, params=params, headers=DNSE_HEADERS)
            r.raise_for_status()
            d = r.json()
            times = d.get("t") or []
            opens = d.get("o") or []
            highs = d.get("h") or []
            lows = d.get("l") or []
            closes = d.get("c") or []
            vols = d.get("v") or []
            result = []
            for i, t in enumerate(times):
                result.append({
                    "timestamp": t,
                    "time": datetime.fromtimestamp(t).strftime("%H:%M"),
                    "open": opens[i] if i < len(opens) else 0,
                    "high": highs[i] if i < len(highs) else 0,
                    "low": lows[i] if i < len(lows) else 0,
                    "close": closes[i] if i < len(closes) else 0,
                    "volume": int(vols[i]) if i < len(vols) else 0,
                })
            return result
        except Exception as e:
            logger.error(f"DNSE intraday error for {symbol}: {e}")
            return []

# ─── News (Google News RSS) ──────────────────────────────────────────────────

async def get_stock_news(symbol: str, limit: int = 5) -> list:
    """Lấy tin tức mới nhất về mã cổ phiếu từ Google News RSS."""
    # Encode url: q={symbol}+cổ+phiếu
    url = f"https://news.google.com/rss/search?q={symbol}+cổ+phiếu&hl=vi&gl=VN&ceid=VN:vi"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        try:
            r = await c.get(url)
            r.raise_for_status()
            
            # Parse XML
            root = ET.fromstring(r.text)
            news_list = []
            
            # Find all item elements under channel
            for item in root.findall(".//item"):
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                pubDate = item.findtext("pubDate") or ""
                source = item.findtext("source") or "Google News"
                
                # Cleanup title (remove the trailing " - Source Name" if present)
                if " - " in title:
                    title = " - ".join(title.split(" - ")[:-1])
                    
                news_list.append({
                    "title": title,
                    "link": link,
                    "date": pubDate,
                    "source": source
                })
                
                if len(news_list) >= limit:
                    break
                    
            return news_list
        except Exception as e:
            logger.error(f"News fetch error for {symbol}: {e}")
            return []

# ─── Current Quote ────────────────────────────────────────────────────────────

async def get_current_quote(symbol: str) -> dict:
    """Lấy giá mới nhất – kết hợp daily (yfinance) + intraday (DNSE)"""
    # Get intraday first (most recent price if market is open)
    intraday = await get_intraday_data(symbol, minutes=60)

    # Get last daily close as baseline
    daily = await get_historical_data(symbol, days=5)

    if not daily:
        return {"symbol": symbol.upper(), "price": 0, "change": 0, "change_pct": 0}

    last = daily[-1]
    prev = daily[-2] if len(daily) >= 2 else last
    current_price = last["close"]

    # If we have intraday data, use the most recent intraday close
    if intraday:
        current_price = intraday[-1]["close"]

    change = current_price - prev["close"]
    change_pct = (change / prev["close"] * 100) if prev["close"] else 0

    is_market_open = bool(intraday)
    return {
        "symbol": symbol.upper(),
        "price": current_price,
        "change": round(change, 0),
        "change_pct": round(change_pct, 2),
        "volume": intraday[-1]["volume"] if intraday else last["volume"],
        "date": last["date"],
        "market_open": is_market_open,
    }

# ─── Market Indices ───────────────────────────────────────────────────────────

def _fetch_index_sync(yf_ticker: str) -> dict:
    return {"value": 0, "change": 0, "change_pct": 0}

async def get_market_overview() -> dict:
    """Tổng quan 3 chỉ số thị trường – dùng DNSE, có cache"""
    cache_key = "overview"
    cached = await _get_cache(_market_overview_cache, cache_key)
    if cached is not None:
        return cached

    tasks = {key: _fetch_dnse_index(sym) for key, sym in INDEX_MAP.items()}
    overview = {}
    warnings = []
    for key, coro in tasks.items():
        try:
            result = await coro
            if result.get("value"):
                overview[key] = result
            else:
                overview[key] = {"value": 0, "change": 0, "change_pct": 0}
                warnings.append(f"{key}: Không có dữ liệu từ DNSE")
        except Exception:
            overview[key] = {"value": 0, "change": 0, "change_pct": 0}
            warnings.append(f"{key}: Lỗi kết nối DNSE")

    if warnings:
        overview["_warnings"] = warnings

    await _set_cache(_market_overview_cache, cache_key, overview, MARKET_OVERVIEW_CACHE_TTL)
    return overview

# ─── Top Movers ───────────────────────────────────────────────────────────────

POPULAR_STOCKS = [
    "VNM", "VIC", "VHM", "HPG", "MSN", "VCB", "BID", "CTG", "TCB",
    "MBB", "VPB", "ACB", "STB", "SSI", "VND", "HDB", "FPT", "MWG",
    "PNJ", "REE", "DGC", "DCM", "DPM", "NLG", "KDH",
]

async def get_top_movers(n: int = 10) -> dict:
    """Top tăng/giảm mạnh – dùng DNSE daily"""
    cache_key = int(n)
    cached = await _get_cache(_top_movers_cache, cache_key)
    if cached is not None:
        return cached

    async def fetch_one(sym):
        data = await get_historical_data(sym, days=5)
        if len(data) >= 2:
            last, prev = data[-1], data[-2]
            if prev["close"] > 0:
                change_pct = (last["close"] - prev["close"]) / prev["close"] * 100
                return {"symbol": sym, "price": last["close"], "change_pct": round(change_pct, 2), "volume": last["volume"]}
        return None

    results = await asyncio.gather(*[fetch_one(s) for s in POPULAR_STOCKS], return_exceptions=True)
    movers = [r for r in results if isinstance(r, dict) and r]
    movers.sort(key=lambda x: x["change_pct"])
    result = {
        "top_gainers": list(reversed(movers[-n:])),
        "top_losers": movers[:n],
    }
    await _set_cache(_top_movers_cache, cache_key, result, TOP_MOVERS_CACHE_TTL)
    return result


async def get_all_symbols() -> list:
    """Lấy danh sách tất cả mã CK từ Wifeed (chỉ các mã hợp lệ, bỏ qua OTC/DELISTING)"""
    cache_key = "all_symbols"
    cached = await _get_cache(_historical_cache, cache_key)
    if cached is not None:
        return cached

    url = "https://wifeed.vn/api/thong-tin-co-phieu/danh-sach-ma-chung-khoan"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            data = r.json()
            stocks = data.get("data", data.get(list(data.keys())[0], []))
            
            valid_stocks = []
            for s in stocks:
                if isinstance(s, dict):
                    san = s.get("san", "").upper()
                    code = s.get("code", "").upper()
                    if san in ["HOSE", "HNX", "UPCOM"] and len(code) == 3:
                        valid_stocks.append(code)
            
            # Save to cache for 24h
            await _set_cache(_historical_cache, cache_key, valid_stocks, 86400)
            return valid_stocks
    except Exception as e:
        logger.error(f"Error fetching all symbols from Wifeed: {e}")
        return POPULAR_STOCKS
