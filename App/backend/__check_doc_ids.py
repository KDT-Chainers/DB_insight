import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import json
from pathlib import Path
from config import EMBEDDED_DB_DOC

ids_path = EMBEDDED_DB_DOC / 'doc_page_ids.json'
raw = json.loads(ids_path.read_text(encoding='utf-8'))
# Handle both list and {"ids": [...]} formats
if isinstance(raw, dict) and 'ids' in raw:
    ids = raw['ids']
elif isinstance(raw, list):
    ids = raw
else:
    # flat dict: keys are IDs
    ids = list(raw.keys())

print(f'Total doc_page_ids: {len(ids)}')
print(f'First 3 IDs: {ids[:3]}')

def doc_key(rid):
    parts = str(rid).replace('\\', '/').split('/')
    return parts[1] if len(parts) >= 3 else (parts[0] if len(parts) >= 2 else rid)

unique_docs = {}
for rid in ids:
    dk = doc_key(rid)
    unique_docs[dk] = unique_docs.get(dk, 0) + 1

print(f'Unique documents: {len(unique_docs)}')

sw_docs  = {k:v for k,v in unique_docs.items() if any(x in k.lower() for x in ['sw','소프트웨어','software'])}
ai_docs  = {k:v for k,v in unique_docs.items() if any(x in k.lower() for x in ['ai','인공지능','artificial','spri','brief'])}
sam_docs = {k:v for k,v in unique_docs.items() if any(x in k.lower() for x in ['samsung','삼성'])}
fod_docs = {k:v for k,v in unique_docs.items() if any(x in k.lower() for x in ['food','식량','fao','농업'])}

print('\n=== SW docs ===')
for k,v in sorted(sw_docs.items()): print(f'  {k}: {v} pages')
print('\n=== AI docs ===')
for k,v in sorted(ai_docs.items()): print(f'  {k}: {v} pages')
print('\n=== Samsung docs ===')
for k,v in sorted(sam_docs.items()): print(f'  {k}: {v} pages')
print('\n=== Food docs ===')
for k,v in sorted(fod_docs.items()): print(f'  {k}: {v} pages')

print('\n=== ALL DOCS ===')
for k,v in sorted(unique_docs.items()):
    print(f'  {k}: {v} pages')
