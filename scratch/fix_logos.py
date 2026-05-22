import os, re
logo_block = """  <a href="/" class="logo">
    <img src="/icons/icon.svg" style="width:34px;height:34px;border-radius:9px;box-shadow: 0 4px 12px rgba(0,0,0,0.5);" alt="Logo" />
    <div><div class="logo-text">StockVN</div><div class="logo-sub">Phân Tích Cổ Phiếu</div></div>
  </a>"""
d = 'd:/stock-analyzer/frontend'
for f in os.listdir(d):
    if f.endswith('.html'):
        p = os.path.join(d, f)
        with open(p, 'r', encoding='utf-8') as file:
            c = file.read()
        new_c = re.sub(r'<a href="[^"]*" class="logo">.*?</a>', logo_block, c, flags=re.DOTALL)
        if new_c != c:
            with open(p, 'w', encoding='utf-8') as file:
                file.write(new_c)
            print('Updated', f)
