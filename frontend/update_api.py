api_path = 'd:/stock-analyzer/frontend/js/api.js'
with open(api_path, 'r', encoding='utf-8') as f:
    js = f.read()

prefix = """
// API configuration
// When deploying to Cloudflare, change this to your backend domain (e.g., 'https://api.stockvn.com')
// Leave empty string '' to use the same domain (for local testing)
const API_BASE_URL = '';

function getApiUrl(endpoint) {
    if (API_BASE_URL) {
        return API_BASE_URL + endpoint;
    }
    return endpoint;
}
"""

if 'API_BASE_URL' not in js:
    js = prefix + js

js = js.replace("fetch('/api/", "fetch(getApiUrl('/api/")
js = js.replace("fetch(`/api/", "fetch(getApiUrl(`/api/")

# Make sure we didn't add multiple getApiUrl
js = js.replace("getApiUrl(getApiUrl(", "getApiUrl(")

with open(api_path, 'w', encoding='utf-8') as f:
    f.write(js)

print('Updated api.js for Cloudflare')
