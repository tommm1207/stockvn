import glob, re

# Update storage.js
storage_path = 'd:/stock-analyzer/frontend/js/storage.js'
with open(storage_path, 'r', encoding='utf-8') as f:
    js = f.read()
    
js = js.replace('function getClientId() {', '''
window.onTelegramAuth = function(user) {
  localStorage.setItem('telegram_chat_id', user.id);
  localStorage.setItem('telegram_user', JSON.stringify(user));
  alert('Đăng nhập thành công! Đã đồng bộ với Telegram của ' + user.first_name);
  location.reload();
}
function logoutTelegram() {
  localStorage.removeItem('telegram_chat_id');
  localStorage.removeItem('telegram_user');
  location.reload();
}
function getClientId() {
  const tgId = localStorage.getItem('telegram_chat_id');
  if (tgId) return String(tgId);
''')
with open(storage_path, 'w', encoding='utf-8') as f:
    f.write(js)

# Update watchlist.html and portfolio.html
widget_html = '''
  <div id="tg-login-container" style="background:rgba(61,155,255,0.1); border:1px solid rgba(61,155,255,0.3); border-radius:8px; padding:16px; margin-bottom:20px; display:flex; flex-direction:column; align-items:center; gap:12px; text-align:center;">
    <div style="font-size:14px; color:var(--text);">
      <b style="color:#3d9bff;">💡 Mẹo:</b> Đăng nhập bằng Telegram để đồng bộ danh mục này với Bot.
    </div>
    <div id="tg-widget-placeholder">
      <script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-login="ptchungkhoan_bot" data-size="large" data-onauth="onTelegramAuth(user)" data-request-access="write"></script>
    </div>
    <div id="tg-user-info" style="display:none; font-size:14px; color:#00d68f; font-weight:bold;">
      ✅ Đã đồng bộ với Telegram: <span id="tg-name"></span> 
      <a href="javascript:void(0)" onclick="logoutTelegram()" style="color:#ff4757; margin-left:8px; font-weight:normal; text-decoration:underline;">Đăng xuất</a>
    </div>
  </div>
  
  <script>
    document.addEventListener('DOMContentLoaded', () => {
      const tgUser = localStorage.getItem('telegram_user');
      if (tgUser) {
        document.getElementById('tg-widget-placeholder').style.display = 'none';
        document.getElementById('tg-user-info').style.display = 'block';
        document.getElementById('tg-name').textContent = JSON.parse(tgUser).first_name;
      }
    });
  </script>
'''

for page in ['watchlist.html', 'portfolio.html']:
    p = f'd:/stock-analyzer/frontend/{page}'
    with open(p, 'r', encoding='utf-8') as f:
        html = f.read()
    
    if '<div class="table-container">' in html and 'tg-login-container' not in html:
        html = html.replace('<div class="table-container">', widget_html + '\n<div class="table-container">', 1)
        
    inline_get_client = re.search(r'function getClientId\(\).*?\}', html, re.DOTALL)
    if inline_get_client:
        html = html.replace(inline_get_client.group(0), '''
        function getClientId() {
          const tgId = localStorage.getItem('telegram_chat_id');
          if (tgId) return String(tgId);
          let id = localStorage.getItem('stockvn_client_id');
          if (!id) {
            id = 'web_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('stockvn_client_id', id);
          }
          return id;
        }
        window.onTelegramAuth = function(user) {
          localStorage.setItem('telegram_chat_id', user.id);
          localStorage.setItem('telegram_user', JSON.stringify(user));
          alert('Đăng nhập thành công!');
          location.reload();
        };
        function logoutTelegram() {
          localStorage.removeItem('telegram_chat_id');
          localStorage.removeItem('telegram_user');
          location.reload();
        }
        ''')
        
    with open(p, 'w', encoding='utf-8') as f:
        f.write(html)

print('Injected Telegram Login')
