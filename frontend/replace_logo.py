import glob

html_files = glob.glob('d:/stock-analyzer/frontend/*.html')

old_logo = '<div class="logo-icon"><svg width="18" height="18" viewBox="0 0 24 24"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg></div>'
new_logo = '<img src="/icons/icon.svg" style="width:34px;height:34px;border-radius:9px;box-shadow: 0 4px 12px rgba(0,0,0,0.5);" alt="Logo" />'

for f in html_files:
    if 'chatbot.html' in f: continue
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
        
    content = content.replace(old_logo, new_logo)
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)

print('Updated logos in all HTML files')
