"""scripts/_bench_common.py — 평가 스크립트 공유 라이브러리.

ContentGoldDB, BGE-M3 인코더, content-aware 메트릭 상수를 여기에 집중.
  - local_bench_v2.py
  - e2e_eval.py
  - perf_benchmark.py
세 스크립트가 공통으로 import.

NOTE: 이 모듈은 App/backend 가 sys.path 에 들어 있다고 가정 (호출 스크립트가
      설정해야 함).
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

# ── 데이터 경로 ──────────────────────────────────────────────────────────────
DATA_DIR = ROOT / "Data" / "embedded_DB"
CAPTION_TRIPLE_PATH = DATA_DIR / "Img" / "captions_triple.jsonl"
MOVIE_SEGMENTS_PATH = DATA_DIR / "Movie" / "segments.json"
MUSIC_SEGMENTS_PATH = DATA_DIR / "Rec" / "segments.json"
DOC_BODY_TEXTS_PATH = DATA_DIR / "Doc" / "_body_texts.json"
IMG_IDS_PATH        = DATA_DIR / "Img" / "img_ids.json"
DOC_IDS_PATH        = DATA_DIR / "Doc" / "doc_page_ids.json"
MOVIE_IDS_PATH      = DATA_DIR / "Movie" / "movie_ids.json"
MUSIC_IDS_PATH      = DATA_DIR / "Rec" / "music_ids.json"

# ── content-aware gold 임계값 (도메인별) ─────────────────────────────────────
CONTENT_THETA: dict[str, float] = {
    # P3 (2026-04-25): 절대 θ + K_MIN/K_MAX clamp 하이브리드.
    # θ 만으로는 쿼리별 코사인 분포 편차 (movie max 0.43~0.63) 를 흡수 못함.
    # gold = top-K  where K = clip(|sims≥θ|, K_MIN, K_MAX)
    "image":    0.50,
    "doc_page": 0.45,
    "movie":    0.35,
    "music":    0.30,
}

# K_MIN: gold 가 K_MIN 미만이면 top K_MIN 으로 확장 (sparse corpus, 좁은 분포)
# K_MAX: gold 가 K_MAX 초과면 top K_MAX 로 축소 (평탄 분포의 noise 차단)
CONTENT_KMIN: dict[str, int] = {"image": 10, "doc_page": 20, "movie": 20, "music": 3}
CONTENT_KMAX: dict[str, int] = {"image": 300, "doc_page": 2000, "movie": 200, "music": 14}

# ── BGE-M3 인코더 (lazy 싱글톤) ──────────────────────────────────────────────
_bgem3_ok: Optional[bool] = None   # None = 아직 미확인
_embed_fn = None
_embed_passage_fn = None  # batch passage encoder (max_length=1024)


def _ensure_encoder() -> bool:
    global _bgem3_ok, _embed_fn, _embed_passage_fn
    if _bgem3_ok is not None:
        return _bgem3_ok
    try:
        import embedders.trichef.bgem3_caption_im as _enc
        _embed_fn = _enc.embed_query
        _embed_passage_fn = _enc.embed_passage
        _bgem3_ok = True
        print("[bench] BGE-M3 인코더 로드 성공")
    except Exception as e:
        warnings.warn(f"[bench] BGE-M3 로드 실패 → content metric 비활성화: {e}")
        _bgem3_ok = False
    return _bgem3_ok


# ── content-aware gold DB ─────────────────────────────────────────────────────

class ContentGoldDB:
    """도메인별 (id → text) 매핑 + 쿼리별 gold id 집합 반환.

    O(Q+N) 최적화: 도메인별 corpus 를 1회 batch 인코딩하여 (N, D) 행렬로
    캐시 (`_mats`, `_ids_in_order`). gold_ids() 는 쿼리 1회 인코딩 후
    (1, D) @ (D, N) dot product 로 즉시 N 개 cosine 계산.
    """

    def __init__(self):
        self._dbs: dict[str, dict[str, str]] = {}   # domain → {id: text}
        self._mats: dict[str, "np.ndarray"] = {}    # domain → (N, D) L2-norm
        self._ids_in_order: dict[str, list[str]] = {}  # domain → [id..N]
        self._encoded: set[str] = set()             # domain 인코딩 완료 mark
        self._ready: dict[str, bool] = {}
        self._build_all()

    # ── 구축 ─────────────────────────────────────────────────────────────────

    def _build_all(self):
        self._dbs["image"]    = self._load_image()
        self._dbs["doc_page"] = self._load_doc()
        self._dbs["movie"]    = self._load_av(MOVIE_SEGMENTS_PATH, MOVIE_IDS_PATH)
        self._dbs["music"]    = self._load_av(MUSIC_SEGMENTS_PATH, MUSIC_IDS_PATH)

    def _load_image(self) -> dict[str, str]:
        """captions_triple.jsonl → {rel: L1+L2+L3}"""
        db: dict[str, str] = {}
        if not CAPTION_TRIPLE_PATH.exists():
            print(f"[bench] captions_triple.jsonl 없음 ({CAPTION_TRIPLE_PATH}) → image content None")
            return db
        try:
            with CAPTION_TRIPLE_PATH.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rel = obj.get("rel", "")
                    parts = [obj.get(k, "") for k in ("L1", "L2", "L3") if obj.get(k)]
                    text = " ".join(parts)
                    if rel and text:
                        db[rel] = text
            print(f"[bench] image caption DB: {len(db)} 항목")
        except Exception as e:
            print(f"[bench] image caption 로드 오류: {e}")
        return db

    @staticmethod
    def _load_ids(ids_path: Path) -> list[str]:
        """ids.json 로드 + dict {"ids":[...]} 자동 unwrap. 실패 시 빈 list."""
        if not ids_path.exists():
            return []
        try:
            raw = json.loads(ids_path.read_bytes().decode("utf-8", errors="replace"))
        except Exception:
            return []
        if isinstance(raw, dict):
            raw = raw.get("ids", [])
        return list(raw) if isinstance(raw, list) else []

    def _load_doc(self) -> dict[str, str]:
        """_body_texts.json → {id: text}  (list[str] or dict[str,str])"""
        db: dict[str, str] = {}
        if not DOC_BODY_TEXTS_PATH.exists():
            print("[bench] _body_texts.json 없음 → doc_page content None")
            return db
        try:
            raw = json.loads(DOC_BODY_TEXTS_PATH.read_bytes().decode("utf-8", errors="replace"))
            if isinstance(raw, list):
                ids_raw = self._load_ids(DOC_IDS_PATH)
                for idx, txt in enumerate(raw):
                    if idx < len(ids_raw) and txt:
                        db[ids_raw[idx]] = str(txt)
            elif isinstance(raw, dict):
                for k, v in raw.items():
                    if v:
                        db[k] = str(v)
            print(f"[bench] doc_page body DB: {len(db)} 항목")
        except Exception as e:
            print(f"[bench] doc body 로드 오류: {e}")
        return db

    def _load_av(self, seg_path: Path, ids_path: Path) -> dict[str, str]:
        """segments.json → {segment_id: stt_text}
        segment_id 는 unified_engine 이 사용하는 ids.json 의 항목과 동일.
        segments 의 file + frame_idx/window_idx 조합이 key."""
        db: dict[str, str] = {}
        if not seg_path.exists():
            print(f"[bench] {seg_path.name} 없음 → {seg_path.parent.name} content None")
            return db
        try:
            raw = json.loads(seg_path.read_bytes().decode("utf-8", errors="replace"))
            ids_raw = self._load_ids(ids_path)
            ids_set = set(ids_raw)

            for seg in raw:
                file_ = seg.get("file", seg.get("file_name", ""))
                fidx  = seg.get("frame_idx", seg.get("window_idx", 0))
                stt   = seg.get("stt_text", seg.get("text", ""))
                if not stt:
                    continue
                seg_id = f"{file_}::{fidx}"
                if file_ in ids_set:
                    db[file_] = (db.get(file_, "") + " " + stt).strip()
                else:
                    db[seg_id] = stt
            print(f"[bench] {seg_path.parent.name} STT DB: {len(db)} 항목")
        except Exception as e:
            print(f"[bench] {seg_path.name} 로드 오류: {e}")
        return db

    # ── gold 산출 ─────────────────────────────────────────────────────────────

    def _encode_corpus(self, domain: str) -> bool:
        """도메인 corpus 를 1회 batch 인코딩하여 (N, D) 행렬 캐시.
        성공 True / 실패(또는 빈 db) False."""
        if domain in self._encoded:
            return domain in self._mats
        self._encoded.add(domain)
        if not _ensure_encoder():
            return False
        db = self._dbs.get(domain) or {}
        if not db:
            return False
        import numpy as np
        ids = list(db.keys())
        texts = [db[i] for i in ids]
        try:
            mat = _embed_passage_fn(texts, batch_size=32, max_length=1024)
        except Exception as e:
            warnings.warn(f"[bench] {domain} corpus 인코딩 실패: {e}")
            return False
        self._mats[domain] = np.asarray(mat, dtype=np.float32)
        self._ids_in_order[domain] = ids
        print(f"[bench] {domain} corpus 인코딩 완료 — shape={self._mats[domain].shape}")
        return True

    def gold_ids(self, query: str, domain: str) -> Optional[set[str]]:
        """BGE-M3 코사인 ≥ θ 인 id 집합. 인코더 없으면 None.

        O(N) 비용: 쿼리 1회 인코딩 + 캐시된 (N,D) 행렬과 dot product.
        """
        if not _ensure_encoder():
            return None
        if not self._encode_corpus(domain):
            return None

        import numpy as np
        try:
            q = _embed_fn(query)
            q_vec = np.asarray(q, dtype=np.float32).reshape(-1)
        except Exception as e:
            warnings.warn(f"[bench] 쿼리 임베딩 오류: {e}")
            return None

        mat = self._mats[domain]                  # (N, D) L2-norm
        sims = mat @ q_vec                        # (N,) cosine
        ids = self._ids_in_order[domain]
        n_total = len(ids)

        # P3 하이브리드: top-K (K = clip(|sims≥θ|, K_MIN, K_MAX))
        theta = CONTENT_THETA.get(domain, 0.50)
        k_min = max(0, CONTENT_KMIN.get(domain, 0))
        k_max = max(k_min, CONTENT_KMAX.get(domain, n_total))
        k_max = min(k_max, n_total)

        n_pass = int((sims >= theta).sum())
        K = max(k_min, min(n_pass, k_max))
        if K <= 0:
            return set()
        if K >= n_total:
            top_idx = np.arange(n_total)
        else:
            top_idx = np.argpartition(-sims, K - 1)[:K]
        return {ids[int(i)] for i in top_idx}


# ── 결과 집계 헬퍼 ────────────────────────────────────────────────────────────

def _precision_at_k(hits: list, gold: Optional[set[str]], id_fn) -> Optional[float]:
    """gold 가 None 이거나 비면 None. 아니면 precision@k."""
    if gold is None:
        return None
    if not gold:
        return None
    matched = sum(1 for h in hits if id_fn(h) in gold)
    return round(matched / max(len(hits), 1), 4)
