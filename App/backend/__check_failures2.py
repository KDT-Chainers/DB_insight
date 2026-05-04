import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.query_expand import expand_bilingual as ebil

# Check new vocabulary
print("=== expand_bilingual vocabulary check ===")
print(f"'실태조사' -> {ebil('실태조사')}")
print(f"'survey' -> {ebil('survey')}")
print(f"'인공지능산업' -> {ebil('인공지능산업')}")
print(f"'소프트웨어산업' -> {ebil('소프트웨어산업')}")
print(f"'2024 SW산업 실태조사 보고서' -> {ebil('2024 SW산업 실태조사 보고서')}")
print(f"'2024 software industry survey Korea' -> {ebil('2024 software industry survey Korea')}")
print()

print("Loading TRI-CHEF engine...")
t0 = time.time()
from services.trichef.unified_engine import TriChefEngine
engine = TriChefEngine()
print(f"  ready in {time.time()-t0:.1f}s\n")

TOP_K = 5

def _doc_key(rid):
    parts = str(rid).replace('\\', '/').split('/')
    return parts[1] if len(parts) >= 3 else (parts[0] if len(parts) >= 2 else rid)

def run(label, ko_q, en_q, domain):
    ko_exp = ebil(ko_q)
    en_exp = ebil(en_q)
    print(f"[{label}]")
    print(f"  KO: '{ko_q}' -> '{ko_exp[:100]}'")
    print(f"  EN: '{en_q}' -> '{en_exp[:100]}'")

    r_ko = engine.search(ko_exp, domain=domain, topk=TOP_K, use_lexical=True, use_asf=True)
    r_en = engine.search(en_exp, domain=domain, topk=TOP_K, use_lexical=True, use_asf=True)
    ko_ids = [_doc_key(r.id) for r in r_ko]
    en_ids = [_doc_key(r.id) for r in r_en]

    print(f"  KO top-5: {ko_ids}")
    print(f"  EN top-5: {en_ids}")
    ov = len(set(ko_ids[:3]) & set(en_ids[:3])) / len(set(ko_ids[:3]) | set(en_ids[:3])) if (ko_ids[:3] or en_ids[:3]) else 1.0
    tag = "PASS" if ov >= 0.33 else "FAIL"
    print(f"  overlap@3 = {ov:.2f}  [{tag}]\n")
    return ov

run("AI_doc_new",  "2024 인공지능산업 실태조사",     "2024 AI industry survey report",        "doc_page")
run("SW_doc_new",  "2024 SW산업 실태조사 보고서",    "2024 software industry survey Korea",   "doc_page")
