import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.query_expand import expand_bilingual as ebil

print("Loading TRI-CHEF engine...")
t0 = time.time()
from services.trichef.unified_engine import TriChefEngine
engine = TriChefEngine()
print(f"  ready in {time.time()-t0:.1f}s")

TOP_K = 5

def _doc_key(rid):
    parts = str(rid).replace('\\', '/').split('/')
    return parts[1] if len(parts) >= 3 else (parts[0] if len(parts) >= 2 else rid)

def run(label, ko_q, en_q, domain):
    ko_exp = ebil(ko_q)
    en_exp = ebil(en_q)
    print(f"\n[{label}] KO='{ko_q}' → expanded='{ko_exp[:80]}'")
    print(f"[{label}] EN='{en_q}'")

    if domain in ('image', 'doc_page'):
        r_ko = engine.search(ko_exp, domain=domain, topk=TOP_K, use_lexical=True, use_asf=True)
        r_en = engine.search(en_exp, domain=domain, topk=TOP_K, use_lexical=True, use_asf=True)
        if domain == 'doc_page':
            ko_ids = [_doc_key(r.id) for r in r_ko]
            en_ids = [_doc_key(r.id) for r in r_en]
        else:
            ko_ids = [r.id for r in r_ko]
            en_ids = [r.id for r in r_en]
        print(f"  KO top-5:")
        for r in r_ko:
            key = _doc_key(r.id) if domain=='doc_page' else r.id.split('/')[-1].split('\\')[-1]
            print(f"    score={r.score:.3f} conf={r.confidence:.2f}  {key[:80]}")
        print(f"  EN top-5:")
        for r in r_en:
            key = _doc_key(r.id) if domain=='doc_page' else r.id.split('/')[-1].split('\\')[-1]
            print(f"    score={r.score:.3f} conf={r.confidence:.2f}  {key[:80]}")
    else:
        r_ko = engine.search_av(ko_q, domain=domain, topk=TOP_K)
        r_en = engine.search_av(en_q, domain=domain, topk=TOP_K)
        ko_ids = [r.file_name for r in r_ko]
        en_ids = [r.file_name for r in r_en]
        print(f"  KO top-3:"); [print(f"    {r.file_name[:70]}") for r in r_ko[:3]]
        print(f"  EN top-3:"); [print(f"    {r.file_name[:70]}") for r in r_en[:3]]

    ov = len(set(ko_ids[:3]) & set(en_ids[:3])) / len(set(ko_ids[:3]) | set(en_ids[:3])) if (ko_ids[:3] or en_ids[:3]) else 1.0
    tag = "PASS" if ov >= 0.33 else "FAIL"
    print(f"  overlap@3 = {ov:.2f}  [{tag}]")
    return ov

# === Failing cases ===
run("cat_img",    "고양이",            "cat feline",                           "image")
run("AI_doc",     "인공지능 AI 산업 동향",  "artificial intelligence industry trends","doc_page")
run("SW_doc",     "소프트웨어 SW 산업",    "software industry survey report",      "doc_page")

# === More specific doc queries (candidate fix) ===
print("\n" + "="*60)
print("CANDIDATE SPECIFIC QUERIES:")
run("AI_doc_v2",  "2024 인공지능산업 실태조사",  "2024 AI industry survey report",     "doc_page")
run("SW_doc_v2",  "2024 SW산업 실태조사",        "2024 software industry survey",      "doc_page")
