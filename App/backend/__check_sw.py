import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from services.query_expand import expand_bilingual as ebil

print("Loading engine...")
from services.trichef.unified_engine import TriChefEngine
engine = TriChefEngine()
print("ready\n")

def _doc_key(rid):
    parts = str(rid).replace('\\', '/').split('/')
    return parts[1] if len(parts) >= 3 else rid

def run(label, ko_q, en_q):
    ko_exp = ebil(ko_q)
    en_exp = ebil(en_q)
    print(f"[{label}]")
    print(f"  KO exp: '{ko_exp[:110]}'")
    print(f"  EN exp: '{en_exp[:110]}'")
    r_ko = engine.search(ko_exp, domain='doc_page', topk=5, use_lexical=True, use_asf=True)
    r_en = engine.search(en_exp, domain='doc_page', topk=5, use_lexical=True, use_asf=True)
    ko_ids = [_doc_key(r.id) for r in r_ko]
    en_ids = [_doc_key(r.id) for r in r_en]
    print(f"  KO: {ko_ids[:3]}")
    print(f"  EN: {en_ids[:3]}")
    ov = len(set(ko_ids[:3]) & set(en_ids[:3])) / len(set(ko_ids[:3]) | set(en_ids[:3])) if (set(ko_ids[:3]) | set(en_ids[:3])) else 1.0
    print(f"  overlap@3 = {ov:.2f}  {'PASS' if ov>=0.33 else 'FAIL'}\n")

# try annual report query
run("SW_annual", "2023년 소프트웨어산업 연간보고서", "2023 software industry annual report")
run("SW_annual2", "소프트웨어산업 연간보고서", "software industry annual report")
run("SW_survey23", "2023년 소프트웨어 실태조사", "2023 software industry survey")
