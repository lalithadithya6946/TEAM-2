import os
import urllib.request
import re

BASE_DIR = r"c:\Users\lalit\OneDrive\Desktop\CAPSTONE PROJECT CCTV"
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

CSS_DIR = os.path.join(STATIC_DIR, "css")
JS_DIR = os.path.join(STATIC_DIR, "js")
FONTS_DIR = os.path.join(STATIC_DIR, "webfonts")

os.makedirs(CSS_DIR, exist_ok=True)
os.makedirs(JS_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)

# Files to download
DOWNLOAD_LINKS = {
    "css/bootstrap.min.css": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css",
    "js/bootstrap.bundle.min.js": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js",
    "css/all.min.css": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css",
    "js/all.min.js": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/js/all.min.js",
    
    # Font Awesome Webfonts
    "webfonts/fa-solid-900.woff2": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-solid-900.woff2",
    "webfonts/fa-solid-900.ttf": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-solid-900.ttf",
    "webfonts/fa-brands-400.woff2": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-brands-400.woff2",
    "webfonts/fa-brands-400.ttf": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-brands-400.ttf",
    "webfonts/fa-regular-400.woff2": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-regular-400.woff2",
    "webfonts/fa-regular-400.ttf": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-regular-400.ttf",
    "webfonts/fa-v4compatibility.woff2": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-v4compatibility.woff2",
    "webfonts/fa-v4compatibility.ttf": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-v4compatibility.ttf"
}

# Download files
for rel_path, url in DOWNLOAD_LINKS.items():
    dest_path = os.path.join(STATIC_DIR, rel_path)
    if not os.path.exists(dest_path):
        print(f"Downloading {rel_path}...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 AppleWebKit/537.36'})
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read()
            with open(dest_path, 'wb') as out_file:
                out_file.write(content)
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            if os.path.exists(dest_path):
                os.remove(dest_path)
    else:
        print(f"{rel_path} already exists.")

# Replacements in templates
REPLACEMENTS = {
    r'https://cdn\.jsdelivr\.net/npm/bootstrap@5\.3\.0/dist/css/bootstrap\.min\.css': r"{{ url_for('static', filename='css/bootstrap.min.css') }}",
    r'https://cdn\.jsdelivr\.net/npm/bootstrap@5\.3\.0/dist/js/bootstrap\.bundle\.min\.js': r"{{ url_for('static', filename='js/bootstrap.bundle.min.js') }}",
    r'https://cdnjs\.cloudflare\.com/ajax/libs/font-awesome/6\.0\.0/css/all\.min\.css': r"{{ url_for('static', filename='css/all.min.css') }}",
    r'https://cdnjs\.cloudflare\.com/ajax/libs/font-awesome/6\.0\.0/js/all\.min\.js': r"{{ url_for('static', filename='js/all.min.js') }}"
}

html_files = [f for f in os.listdir(TEMPLATES_DIR) if f.endswith('.html')]
updated_count = 0

for file in html_files:
    file_path = os.path.join(TEMPLATES_DIR, file)
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    for old_pattern, new_replacement in REPLACEMENTS.items():
        new_content = re.sub(old_pattern, new_replacement, new_content)
        
    if new_content != content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {file}")
        updated_count += 1

print(f"Finished downloading resources and updated {updated_count} HTML files.")
