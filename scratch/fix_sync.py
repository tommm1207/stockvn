import re

with open('backend/data_fetcher.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix get_historical_data
content = content.replace(
    'vnd_r = await client.get(vnd_url)',
    'vnd_r = await client.get(vnd_url, timeout=2.0)'
)

# Fix get_fundamentals
content = content.replace(
    'r = requests.get(f"https://finfo-api.vndirect.com.vn/v4/ratios?q=code:{symbol}", timeout=5)',
    '''async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"https://finfo-api.vndirect.com.vn/v4/ratios?q=code:{symbol}")'''
)

# Fix get_deep_fundamentals
content = content.replace(
    'r = requests.get(url, timeout=5)',
    '''async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(url)'''
)

with open('backend/data_fetcher.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed sync requests')
