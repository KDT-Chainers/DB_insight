"""Doc + Image ASF vocab/token_sets 빠른 재빌드 (sparse 제외).

변경 내용:
  - _DOMAIN_FORCED_KEYWORDS["doc"] 에 한국어 도메인 핵심 어근 추가
  - _DOMAIN_FORCED_KEYWORDS["image"] 에 한국어 시각 핵심어 추가
  - Doc: 캡션 텍스트만 사용 (PDF full-text 제외) → 빠른 실행
  - Image: 캡션 텍스트 + vocab + ASF + sparse 전체 재빌드

결과:
  - Doc ASF token_sets fill rate 향상 (55.2% → 개선 기대)
  - Image ASF vocab에 한국어 키워드 추가
  - 기존 sparse 매트릭스는 유지 (재빌드 안 함)
"""
import sys, time, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from pathlib import Path
from tqdm import tqdm
from config import PATHS
from services.trichef import asf_filter, auto_vocab
from services.trichef.lexical_rebuild import _inject_domain_keywords
from embedders.trichef.caption_io import load_caption, page_idx_from_stem
from embedders.trichef.doc_page_render import stem_key_for

t_start = time.time()

# ═══════════════════════════════════════════════════════════════════
# IMAGE — 캡션 텍스트 + vocab + ASF + sparse 재빌드
# ═══════════════════════════════════════════════════════════════════
print(f"\n[IMAGE] ASF 재빌드 시작 {time.strftime('%H:%M:%S')}")
t0 = time.time()
img_cache = Path(PATHS["TRICHEF_IMG_CACHE"])
img_extract = Path(PATHS["TRICHEF_IMG_EXTRACT"])
img_ids_path = img_cache / "img_ids.json"

img_ids = json.loads(img_ids_path.read_text(encoding="utf-8"))["ids"]
cap_dir = img_extract / "captions"

img_docs = []
img_empty = 0
for i in img_ids:
    txt = load_caption(cap_dir, stem_key_for(i))
    if not txt:
        txt = load_caption(cap_dir, Path(i).stem)
    if not txt:
        img_empty += 1
    img_docs.append(txt)
print(f"  캡션 로드: 총 {len(img_docs)}건, 빈 {img_empty}건")

img_vocab = auto_vocab.build_vocab(img_docs, min_df=2, max_df_ratio=0.5, top_k=8000)
img_vocab = _inject_domain_keywords(img_vocab, "image")
auto_vocab.save_vocab(img_cache / "auto_vocab.json", img_vocab)
print(f"  vocab={len(img_vocab)} (새로 저장)")

img_sets = asf_filter.build_doc_token_sets(img_docs, img_vocab)
asf_filter.save_token_sets(img_cache / "asf_token_sets.json", img_sets)
img_nonempty = sum(1 for s in img_sets if s)
print(f"  token_sets: {img_nonempty}/{len(img_sets)} non-empty "
      f"({100*img_nonempty/len(img_sets):.1f}%) — 저장 완료")
print(f"  [IMAGE] 완료 ({time.time()-t0:.1f}s)")

# ═══════════════════════════════════════════════════════════════════
# DOC — 캡션만 사용하는 빠른 버전 (PDF full-text 제외)
#   이유: PDF reading 은 34663건에서 수 분 소요, 캡션만으로도 ASF 개선 가능
# ═══════════════════════════════════════════════════════════════════
print(f"\n[DOC] ASF 재빌드 시작 (캡션 전용) {time.strftime('%H:%M:%S')}")
t0 = time.time()
doc_cache = Path(PATHS["TRICHEF_DOC_CACHE"])
doc_extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
doc_ids_path = doc_cache / "doc_page_ids.json"

doc_ids = json.loads(doc_ids_path.read_text(encoding="utf-8"))["ids"]
doc_cap_dir = doc_extract / "captions"
print(f"  doc_page_ids: {len(doc_ids)}건")

doc_texts = []
doc_cap_empty = 0
for i in tqdm(doc_ids, desc="Doc captions"):
    parts = Path(i).parts
    if len(parts) < 3 or parts[0] != "page_images":
        doc_texts.append("")
        doc_cap_empty += 1
        continue
    stem = parts[1]
    page_stem = Path(parts[2]).stem
    cap = load_caption(doc_cap_dir / stem, page_stem)
    if not cap:
        cap = load_caption(doc_cap_dir, page_stem)
    if not cap:
        doc_cap_empty += 1
    doc_texts.append(cap or "")

print(f"  캡션 로드 완료: 총 {len(doc_texts)}건, 빈 캡션 {doc_cap_empty}건 "
      f"({time.time()-t0:.1f}s)")

t1 = time.time()
doc_vocab = auto_vocab.build_vocab(doc_texts, min_df=2, max_df_ratio=0.4, top_k=25000)
doc_vocab = _inject_domain_keywords(doc_vocab, "doc")
auto_vocab.save_vocab(doc_cache / "auto_vocab.json", doc_vocab)
print(f"  vocab={len(doc_vocab)} (새로 저장, {time.time()-t1:.1f}s)")

# 강제 키워드 확인
forced_check = ["경제", "인공지능", "기술", "정치", "역사", "교육", "의료", "통계"]
for kw in forced_check:
    if kw in doc_vocab:
        print(f"    vocab[{kw}]: df={doc_vocab[kw].get('df',0)} idf={doc_vocab[kw].get('idf',0):.2f}")
    else:
        print(f"    vocab[{kw}]: MISSING!")

t2 = time.time()
doc_sets = asf_filter.build_doc_token_sets(doc_texts, doc_vocab)
asf_filter.save_token_sets(doc_cache / "asf_token_sets.json", doc_sets)
doc_nonempty = sum(1 for s in doc_sets if s)
print(f"  token_sets: {doc_nonempty}/{len(doc_sets)} non-empty "
      f"({100*doc_nonempty/len(doc_sets):.1f}%) — 저장 완료 ({time.time()-t2:.1f}s)")

# 샘플 확인
sample_with_tokens = next((s for s in doc_sets if s), None)
if sample_with_tokens:
    print(f"  sample token_set (size={len(sample_with_tokens)}): "
          f"{list(sample_with_tokens.keys())[:10]}")

print(f"  [DOC] 완료 ({time.time()-t0:.1f}s)")

print(f"\n[ALL DONE] total={time.time()-t_start:.1f}s  {time.strftime('%H:%M:%S')}")
