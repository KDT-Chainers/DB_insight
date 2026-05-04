import json
from pathlib import Path
from config import EMBEDDED_DB_BGM, EMBEDDED_DB_DOC

meta = json.loads((EMBEDDED_DB_BGM / 'audio_meta.json').read_text(encoding='utf-8'))

calm_entries = [m for m in meta if any(t in m.get('tags',[]) for t in ['slow','calm'])]
fast_entries = [m for m in meta if 'fast' in m.get('tags',[])]
dark_entries = [m for m in meta if 'dark-timbre' in m.get('tags',[])]

print('=== CALM/SLOW samples ===')
for m in calm_entries[:3]:
    print(f"  {m['filename']}: tags={m['tags']} desc={str(m.get('description',''))[:120]}")

print('=== FAST samples ===')
for m in fast_entries[:3]:
    print(f"  {m['filename']}: tags={m['tags']} desc={str(m.get('description',''))[:120]}")

print('=== DARK samples ===')
for m in dark_entries[:3]:
    print(f"  {m['filename']}: tags={m['tags']} desc={str(m.get('description',''))[:120]}")

print(f'\ncounts — calm: {len(calm_entries)}, fast: {len(fast_entries)}, dark: {len(dark_entries)}')

# Doc index
print('\n=== EMBEDDED_DB_DOC ===')
print('path:', EMBEDDED_DB_DOC)
print('exists:', EMBEDDED_DB_DOC.exists())
if EMBEDDED_DB_DOC.exists():
    for f in sorted(EMBEDDED_DB_DOC.iterdir())[:20]:
        sz = f.stat().st_size if f.is_file() else 0
        print(f"  {f.name}  {sz:,}")
