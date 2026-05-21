import glob

html_files = glob.glob('d:/stock-analyzer/frontend/*.html')

pwa_head = """
  <!-- PWA & Mobile First -->
  <link rel="manifest" href="/manifest.json" />
  <meta name="theme-color" content="#0f172a" />
  <link rel="apple-touch-icon" href="/icons/icon-192.png" />
"""

pwa_script = """
<!-- Service Worker Registration -->
<script>
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').then(reg => {
        console.log('SW registered!', reg);
      }).catch(err => console.log('SW registration failed', err));
    });
  }
</script>
"""

for f in html_files:
    if 'chatbot.html' in f: continue
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
        
    if 'manifest.json' not in content:
        content = content.replace('</head>', pwa_head + '</head>')
        
    if 'serviceWorker' not in content:
        content = content.replace('</body>', pwa_script + '</body>')
        
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)

print('Updated all HTML files')
