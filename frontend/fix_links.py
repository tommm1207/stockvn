import glob

for f in glob.glob('frontend/*.html'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Replace logo link
    content = content.replace('<a href="/" class="logo">', '<a href="index.html" class="logo">')
    # Replace nav link for home
    content = content.replace('<a href="/" class="nav-link', '<a href="index.html" class="nav-link')
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
print('Fixed links!')
