import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import json, pickle
from pathlib import Path
from config import EMBEDDED_DB_DOC, DATA_ROOT

print('EMBEDDED_DB_DOC:', EMBEDDED_DB_DOC)
print('exists:', EMBEDDED_DB_DOC.exists())
if EMBEDDED_DB_DOC.exists():
    for f in sorted(EMBEDDED_DB_DOC.iterdir())[:30]:
        sz = f.stat().st_size if f.is_file() else 0
        print(f"  {f.name}  {sz:,}")

# Also check page_images dir for doc structure
page_img_dir = DATA_ROOT / 'raw_DB' / 'page_images'
print('\npage_images dir:', page_img_dir)
print('exists:', page_img_dir.exists())
if page_img_dir.exists():
    subdirs = [d for d in page_img_dir.iterdir() if d.is_dir()]
    print(f'doc subdirs count: {len(subdirs)}')
    for d in subdirs[:10]:
        pages = list(d.glob('*.jpg'))
        print(f"  {d.name}: {len(pages)} pages")

# Check TRI-CHEF cache for doc_page
from pathlib import Path as P
possible_caches = [
    DATA_ROOT / 'extracted_DB' / 'Doc',
    DATA_ROOT / 'embedded_DB' / 'Doc',
]
for cache_dir in possible_caches:
    if cache_dir.exists():
        files = list(cache_dir.iterdir())
        print(f'\n{cache_dir}: {len(files)} items')
        for f in files[:10]:
            sz = f.stat().st_size if f.is_file() else 0
            print(f"  {f.name}  {sz:,}")
