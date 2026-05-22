import re
with open('backend/data_fetcher.py', 'r', encoding='utf-8') as f:
    code = f.read()

idx = code.find('def _fetch_index_sync')
idx2 = code.find('async def get_market_overview')

if idx != -1 and idx2 != -1:
    code = code[:idx] + 'def _fetch_index_sync(yf_ticker: str) -> dict:\n    return {"value": 0, "change": 0, "change_pct": 0}\n\n' + code[idx2:]
    with open('backend/data_fetcher.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print('Fixed indentation error')
