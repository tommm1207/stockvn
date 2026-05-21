import glob

html_files = glob.glob('d:/stock-analyzer/frontend/*.html')

for f in html_files:
    if 'chatbot.html' in f:
        continue
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Add favicon link if missing
    if 'rel="icon"' not in content and '<head>' in content:
        content = content.replace(
            '<head>',
            '<head>\n  <link rel="icon" type="image/svg+xml" href="/icons/icon.svg" />\n  <link rel="icon" type="image/png" sizes="192x192" href="/icons/icon-192.png" />',
            1
        )
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)

print('Added favicon to all HTML files')
