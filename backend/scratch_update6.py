import re

with open('backend/data_fetcher.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Clean up imports
code = re.sub(r'import yfinance as yf\n', '', code)
code = re.sub(r'YF_CACHE_DIR.*?yf\.set_tz_cache_location\(str\(YF_CACHE_DIR\)\)\n', '', code, flags=re.DOTALL)
code = re.sub(r'def vn_ticker\(symbol: str\) -> str:.*?return f"\{symbol\.upper\(\)\}\.VN"\n', '', code, flags=re.DOTALL)

# 2. _fetch_fundamentals_sync
fund_pattern = r'def _fetch_fundamentals_sync\(symbol: str\) -> dict:.*?return \{\}'
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
    }'''
code = re.sub(fund_pattern, new_fund, code, flags=re.DOTALL)

# 3. _fetch_deep_fundamentals_sync
deep_pattern = r'def _fetch_deep_fundamentals_sync\(symbol: str\) -> dict:.*?"balance_sheet": \[\]\}'
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
        logger.warning(f"Error fetching deep fundamentals: {e}")

    return {
        "income_statement": income_stmt,
        "balance_sheet": balance_sheet,
        "cash_flow": {}
    }'''
code = re.sub(deep_pattern, new_deep, code, flags=re.DOTALL)

# 4. _fetch_index_sync
idx_pattern = r'def _fetch_index_sync\(yf_ticker: str\) -> dict:.*?return \{\}'
new_idx = '''def _fetch_index_sync(yf_ticker: str) -> dict:
    return {"value": 0, "change": 0, "change_pct": 0}'''
code = re.sub(idx_pattern, new_idx, code, flags=re.DOTALL)

# Remove any lingering _fetch_yfinance_sync or yf refs
code = code.replace('import yfinance as yf', '')
code = code.replace('"""Top tăng/giảm mạnh – dùng yfinance daily"""', '"""Top tăng/giảm mạnh – dùng DNSE daily"""')

with open('backend/data_fetcher.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("done")
