import re

with open('backend/data_fetcher.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove yf imports
content = re.sub(r'import yfinance as yf\n', '', content)
content = re.sub(r'YF_CACHE_DIR.*?yf\.set_tz_cache_location.*?YF_CACHE_DIR\)\)', '', content, flags=re.DOTALL)
content = re.sub(r'def vn_ticker\(symbol: str\) -> str:.*?return f"\{symbol\.upper\(\)\}\.VN"\n', '', content, flags=re.DOTALL)

# 2. Rewrite historical data
hist_pattern = r'# ─── Historical Daily Data \(yfinance\) ────────────────────────────────────────.*?def _fetch_yfinance_sync.*?return result\n'
new_hist = '''# ─── Historical Daily Data ────────────────────────────────────────

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
    params = {"symbol": symbol, "resolution": "D", "from": start_time, "to": end_time}
    
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
                vnd_r = await client.get(vnd_url)
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
'''
content = re.sub(r'# ─── Historical Daily Data \(yfinance\) ────────────────────────────────────────.*?# ─── Intraday Data \(DNSE\) ────────────────────────────────────────────────────', new_hist + '\n# ─── Intraday Data (DNSE) ────────────────────────────────────────────────────', content, flags=re.DOTALL)

# 3. Rewrite fundamentals
fund_pattern = r'def _fetch_fundamentals_sync\(symbol: str\) -> dict:.*?# ─── Deep Fundamentals \(yfinance\) ──────────────────────────────────────────'
new_fund = '''def _fetch_fundamentals_sync(symbol: str) -> dict:
    fallback_name = get_company_name_sync(symbol)
    market_cap, pe, pb, eps, roe = 0, 0, 0, 0, 0
    try:
        import requests
        r = requests.get(f"https://finfo-api.vndirect.com.vn/v4/ratios?q=code:{symbol}", timeout=5)
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
        logger.warning(f"Error fetching fundamental stats for {symbol} from VNDirect/DNSE: {e}")

    return {
        "name": fallback_name,
        "sector": "Tài chính/Bất động sản/Sản xuất",
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

# ─── Deep Fundamentals (VNDirect) ──────────────────────────────────────────
'''
content = re.sub(fund_pattern, new_fund, content, flags=re.DOTALL)

# 4. Rewrite deep fundamentals
deep_fund = r'def _fetch_deep_fundamentals_sync\(symbol: str\) -> dict:.*?# ─── Market Overview ─────────────────────────────────────────────────────────'
new_deep = '''def _fetch_deep_fundamentals_sync(symbol: str) -> dict:
    income_stmt = {}
    balance_sheet = {}
    try:
        import requests
        url = f"https://finfo-api.vndirect.com.vn/v4/financial_statements?q=code:{symbol}~reportType:QUARTER&sort=-fiscalDate&size=4"
        r = requests.get(url, timeout=5)
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
        logger.warning(f"Error fetching deep fundamentals from VNDirect for {symbol}: {e}")

    return {
        "income_statement": income_stmt,
        "balance_sheet": balance_sheet,
        "cash_flow": {}
    }

# ─── Market Overview ─────────────────────────────────────────────────────────
'''
content = re.sub(deep_fund, new_deep, content, flags=re.DOTALL)

# 5. Rewrite get_latest_price (yfinance fallback removal)
latest_price = r'def _fetch_latest_price_yfinance\(symbol: str\):.*?return None'
content = re.sub(latest_price, '', content, flags=re.DOTALL)

lp2 = r'yf_price = await loop\.run_in_executor\(None, _fetch_latest_price_yfinance, symbol\)\n\s+if yf_price is not None:\n\s+return yf_price'
content = re.sub(lp2, '', content, flags=re.DOTALL)

# 6. Rewrite _fetch_index_sync
idx_sync = r'def _fetch_index_sync\(yf_ticker: str\) -> dict:.*?return \{"value": 0, "change": 0, "change_pct": 0\}'
new_idx = '''def _fetch_index_sync(yf_ticker: str) -> dict:
    return {"value": 0, "change": 0, "change_pct": 0}'''
content = re.sub(idx_sync, new_idx, content, flags=re.DOTALL)


with open('backend/data_fetcher.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated perfectly")
