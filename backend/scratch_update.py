import re

with open('backend/data_fetcher.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Remove yfinance
code = re.sub(r'import yfinance as yf\n', '', code)
code = re.sub(r'def vn_ticker\(symbol: str\) -> str:[\s\S]*?return symbol \+ "\.VN"\n\n', '', code)

# get_historical_data
new_historical = '''async def get_historical_data(symbol: str, days: int = 300) -> list:
    """
    Lấy dữ liệu giá quá khứ theo ngày (D).
    """
    cache_key = f"hist_{symbol}_{days}"
    cached = await _get_cache(_historical_cache, cache_key)
    if cached is not None:
        return cached

    url = "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
    end_time = int(time.time())
    start_time = end_time - (days * 86400)
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
            
            if results:
                try:
                    last_date_str = results[-1]["date"]
                    vnd_url = f"https://finfo-api.vndirect.com.vn/v4/stock_prices?sort=date&q=code:{symbol}~date:gte:{last_date_str}"
                    vnd_r = await client.get(vnd_url)
                    vnd_data = vnd_r.json().get("data", [])
                    if vnd_data:
                        last_vnd = vnd_data[0]
                        f_buy = last_vnd.get("fBuyVol", 0)
                        f_sell = last_vnd.get("fSellVol", 0)
                        results[-1]["foreign_buy"] = f_buy
                        results[-1]["foreign_sell"] = f_sell
                        results[-1]["foreign_net"] = f_buy - f_sell
                except Exception:
                    pass
            
            await _set_cache(_historical_cache, cache_key, results, HISTORICAL_CACHE_TTL)
            return results
    except Exception as e:
        logger.error(f"Lỗi lấy dữ liệu lịch sử DNSE cho {symbol}: {e}")
        return []'''

code = re.sub(r'async def get_historical_data\(symbol: str, days: int = 300\) -> list:[\s\S]*?logger\.error\(f"Lỗi lấy dữ liệu lịch sử cho \{symbol\}: \{e\}"\)\n        return \[\]', new_historical, code)

# fundamentals
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
    }'''

code = re.sub(r'def _fetch_fundamentals_sync\(symbol: str\) -> dict:[\s\S]*?"dividend_yield": info\.get\("dividendYield", 0\)\n        \}', new_fund, code)

# deep fundamentals
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
    }'''

code = re.sub(r'def _fetch_deep_fundamentals_sync\(symbol: str\) -> dict:[\s\S]*?"cash_flow": parse_df\(cf\)\n    \}', new_deep, code)

with open('backend/data_fetcher.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("Updated successfully")
