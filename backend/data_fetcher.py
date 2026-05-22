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
import yfinance as yf
import numpy as np
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

YF_CACHE_DIR = Path(os.getenv("YFINANCE_CACHE_DIR", Path(__file__).parent / ".yfinance_cache"))
YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YF_CACHE_DIR))

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
def vn_ticker(symbol: str) -> str:
    """Chuyển mã CK VN sang Yahoo Finance ticker"""
    return f"{symbol.upper()}.VN"

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

# ─── Historical Daily Data (yfinance) ────────────────────────────────────────

def _fetch_yfinance_sync(ticker_str: str, period: str = "1y") -> list:
    """Đồng bộ – lấy dữ liệu daily từ yfinance"""
    try:
        tk = yf.Ticker(ticker_str)
        df = tk.history(period=period, auto_adjust=True)
        if df.empty:
            return []
        df = df.dropna(subset=["Close"])
        result = []
        for idx, row in df.iterrows():
            date_str = str(idx)[:10]
            result.append({
                "date": date_str,
                "open": round(float(row["Open"]), 0),
                "high": round(float(row["High"]), 0),
                "low": round(float(row["Low"]), 0),
                "close": round(float(row["Close"]), 0),
                "volume": int(row["Volume"]),
            })
        return result
    except Exception as e:
        logger.error(f"yfinance error for {ticker_str}: {e}")
        return []

async def get_historical_data(symbol: str, days: int = 300) -> list:
    """Lấy dữ liệu OHLCV lịch sử từ VNDirect API (Nhanh & Chính xác nhất cho VN)"""
    symbol = symbol.upper()
    cache_key = (symbol, int(days))
    cached = await _get_cache(_historical_cache, cache_key)
    if cached is not None:
        return cached

    now = int(time.time())
    # Tính số ngày giao dịch thực tế (bỏ T7, CN), nên cần query nhiều ngày lịch hơn một chút
    from_time = now - (days + int(days*0.5) + 10) * 86400
    
    url = f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={symbol}&from={from_time}&to={now}"
    
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            data = r.json()
            
            if data.get("s") == "ok":
                t = data.get("t", [])
                o = data.get("o", [])
                h = data.get("h", [])
                l = data.get("l", [])
                c = data.get("c", [])
                v = data.get("v", [])
                
                result = []
                for i in range(len(t)):
                    result.append({
                        "date": datetime.fromtimestamp(t[i]).strftime("%Y-%m-%d"),
                        "open": round(float(o[i]), 2),
                        "high": round(float(h[i]), 2),
                        "low": round(float(l[i]), 2),
                        "close": round(float(c[i]), 2),
                        "volume": int(v[i]),
                    })
                
                # Trả về đúng số lượng nến yêu cầu
                result = result[-days:] if len(result) > days else result
                await _set_cache(_historical_cache, cache_key, result, HISTORICAL_CACHE_TTL)
                return result
            else:
                logger.warning(f"VNDirect trả về lỗi cho {symbol}: {data}")
    except Exception as e:
        logger.error(f"VNDirect API error for {symbol}: {e}")
        
    # Fallback to Yahoo Finance if VNDirect fails
    ticker_str = vn_ticker(symbol)
    period = "1y" if days <= 250 else "2y" if days <= 500 else "5y"
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _fetch_yfinance_sync, ticker_str, period)
    if not data:
        data = await loop.run_in_executor(None, _fetch_yfinance_sync, symbol, period)
        
    result = data[-days:] if len(data) > days else data
    await _set_cache(_historical_cache, cache_key, result, HISTORICAL_CACHE_TTL)
    return result

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
    """Lấy chỉ số cơ bản từ yfinance (.info). Có fallback tự tính từ fast_info và BCTC."""
    try:
        tk = yf.Ticker(vn_ticker(symbol))
        info = {}
        try:
            info = tk.info or {}
        except Exception as e:
            logger.warning(f"info bị chặn cho {symbol}: {e}")
            
        fast = {}
        try:
            fast = tk.fast_info or {}
        except Exception as e:
            logger.warning(f"fast_info bị chặn cho {symbol}: {e}")

        sec = info.get("sector")
        ind = info.get("industry")
        
        market_cap = info.get("marketCap") or fast.get("marketCap")
        shares = info.get("sharesOutstanding") or fast.get("shares")
        high_52w = info.get("fiftyTwoWeekHigh") or fast.get("yearHigh")
        low_52w = info.get("fiftyTwoWeekLow") or fast.get("yearLow")
        avg_vol = info.get("averageVolume") or fast.get("tenDayAverageVolume")
        last_price = fast.get("lastPrice") or info.get("currentPrice")
        
        pe_trailing = info.get("trailingPE")
        eps_trailing = info.get("trailingEps")
        pb = info.get("priceToBook")
        book_value = info.get("bookValue")
        roe = info.get("returnOnEquity")
        debt_to_equity = info.get("debtToEquity")
        
        # Nếu thiếu các chỉ số cơ bản quan trọng, tự tính từ BCTC
        if not pe_trailing or not roe or not pb:
            try:
                dfund = _fetch_deep_fundamentals_sync(symbol)
                inc = dfund.get("income_statement", [])
                bal = dfund.get("balance_sheet", [])
                
                if len(inc) > 0 and shares and last_price:
                    total_net_income = sum([q.get("net_income", 0) for q in inc])
                    if total_net_income != 0:
                        eps_trailing = eps_trailing or (total_net_income / shares)
                        pe_trailing = pe_trailing or (last_price / eps_trailing)
                        
                if len(bal) > 0 and len(inc) > 0:
                    latest_equity = bal[0].get("total_equity", 0)
                    latest_debt = bal[0].get("total_liabilities", 0)
                    if latest_equity > 0:
                        book_value = book_value or (latest_equity / shares) if shares else book_value
                        pb = pb or (last_price / book_value) if book_value else pb
                        total_net_income = sum([q.get("net_income", 0) for q in inc])
                        roe = roe or (total_net_income / latest_equity)
                        debt_to_equity = debt_to_equity or (latest_debt / latest_equity * 100)
            except Exception as e:
                logger.error(f"Lỗi tính toán BCTC dự phòng cho {symbol}: {e}")

        return {
            "name": translate_company_name(symbol, info) if info.get("longName") else symbol,
            "sector": SECTOR_VI.get(sec, sec) if sec else None,
            "industry": INDUSTRY_VI.get(ind, ind) if ind else None,
            "market_cap": market_cap,
            "pe_trailing": pe_trailing,
            "pe_forward": info.get("forwardPE"),
            "pb": pb,
            "eps_trailing": eps_trailing,
            "book_value": book_value,
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "high_52w": high_52w,
            "low_52w": low_52w,
            "avg_volume": avg_vol,
            "shares_outstanding": shares,
            "enterprise_value": info.get("enterpriseValue"),
            "roe": roe,
            "profit_margin": info.get("profitMargins"),
            "revenue_growth": info.get("revenueGrowth"),
            "debt_to_equity": debt_to_equity,
        }
    except Exception as e:
        logger.error(f"Lỗi fetch fundamentals cho {symbol}: {e}")
        return {}


async def get_fundamentals(symbol: str) -> dict:
    """Async wrapper – yfinance là sync nên chạy trong threadpool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_fundamentals_sync, symbol)

def _fetch_deep_fundamentals_sync(symbol: str) -> dict:
    """Lấy dữ liệu BCTC chuyên sâu từ yfinance (theo Quý/Năm)."""
    try:
        tk = yf.Ticker(vn_ticker(symbol))
        
        # Lấy income_stmt (Báo cáo kết quả kinh doanh)
        # Chúng ta ưu tiên lấy theo Quý (quarterly_income_stmt), fallback sang Năm
        df_income = tk.quarterly_income_stmt
        if df_income.empty:
            df_income = tk.income_stmt
            
        df_balance = tk.quarterly_balance_sheet
        if df_balance.empty:
            df_balance = tk.balance_sheet
            
        result = {
            "income_statement": [],
            "balance_sheet": []
        }
        
        # Parse Income Statement (chỉ lấy 4 kỳ gần nhất)
        if not df_income.empty:
            # df_income có columns là datetime, index là các khoản mục
            cols = list(df_income.columns)[:4]
            for col in cols:
                period_data = df_income[col]
                # Safely get values, handling NaN
                revenue = period_data.get("Total Revenue")
                gross_profit = period_data.get("Gross Profit")
                operating_income = period_data.get("Operating Income")
                net_income = period_data.get("Net Income")
                
                result["income_statement"].append({
                    "date": col.strftime("%Y-%m-%d"),
                    "revenue": float(revenue) if not np.isnan(revenue) else 0,
                    "gross_profit": float(gross_profit) if not np.isnan(gross_profit) else 0,
                    "operating_income": float(operating_income) if not np.isnan(operating_income) else 0,
                    "net_income": float(net_income) if not np.isnan(net_income) else 0,
                })
                
        # Parse Balance Sheet (chỉ lấy 4 kỳ gần nhất)
        if not df_balance.empty:
            cols = list(df_balance.columns)[:4]
            for col in cols:
                period_data = df_balance[col]
                total_assets = period_data.get("Total Assets")
                total_liabilities = period_data.get("Total Liabilities Net Minority Interest")
                total_equity = period_data.get("Stockholders Equity")
                
                result["balance_sheet"].append({
                    "date": col.strftime("%Y-%m-%d"),
                    "total_assets": float(total_assets) if not np.isnan(total_assets) else 0,
                    "total_liabilities": float(total_liabilities) if not np.isnan(total_liabilities) else 0,
                    "total_equity": float(total_equity) if not np.isnan(total_equity) else 0,
                })
                
        return result
    except Exception as e:
        logger.error(f"Deep Fundamentals error for {symbol}: {e}")
        return {"income_statement": [], "balance_sheet": []}

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
    try:
        tk = yf.Ticker(yf_ticker)
        df = tk.history(period="5d", auto_adjust=True)
        if df.empty or len(df) < 2:
            return {}
        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(last["Close"])
        prev_close = float(prev["Close"])
        change = close - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        return {
            "value": round(close, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "volume": int(last["Volume"]),
            "date": str(df.index[-1])[:10],
        }
    except Exception as e:
        logger.error(f"Index fetch error for {yf_ticker}: {e}")
        return {}

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
    """Top tăng/giảm mạnh – dùng yfinance daily"""
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
