import re

with open('backend/data_fetcher.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Replace _fetch_fundamentals_sync
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

code = re.sub(r'def _fetch_fundamentals_sync\(symbol: str\) -> dict:[\s\S]*?"dividend_yield": info\.get\("dividendYield", 0\)\n        \}', new_fund, code)

# 2. Replace _fetch_deep_fundamentals_sync
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
code = re.sub(r'def _fetch_deep_fundamentals_sync\(symbol: str\) -> dict:[\s\S]*?"cash_flow": parse_df\(cf\)\n    \}', new_deep, code)

# 3. index sync replace
idx_sync = r'def _fetch_index_sync\(yf_ticker: str\) -> dict:.*?return \{"value": 0, "change": 0, "change_pct": 0\}'
new_idx = '''def _fetch_index_sync(yf_ticker: str) -> dict:
    return {"value": 0, "change": 0, "change_pct": 0}'''
code = re.sub(idx_sync, new_idx, code, flags=re.DOTALL)

with open('backend/data_fetcher.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("done")
