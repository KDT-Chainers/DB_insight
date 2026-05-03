"""bgm_enrich_text.py — BGM 트랙 텍스트 설명 생성 + CLAP 텍스트 임베딩 인덱스 구축.

목적:
  312개 BGM 트랙(001-312.mp4)은 파일명에 의미가 없어 키워드 검색이 불가.
  librosa 특징(태그+파라미터)에서 자연어 설명을 생성하고 CLAP 텍스트 인코더로
  임베딩하여 별도 FAISS 인덱스를 구축 → text-to-text 보조 검색 채널 추가.

사용:
  cd App/backend
  python bin/bgm_enrich_text.py
  (RTX 4070 기준 약 2-5분)

출력:
  Data/embedded_DB/Bgm/text_emb.npy   - CLAP 텍스트 임베딩 (N×512)
  Data/embedded_DB/Bgm/text_index.faiss - FAISS 텍스트 인덱스
  Data/embedded_DB/Bgm/text_ids.json  - 인덱스 순서대로 filename 리스트
  audio_meta.json 에 "description" 필드 추가 (백업 후 덮어씀)
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.bgm import bgm_config
from services.bgm.clap_encoder import encode_text, _ensure_loaded as clap_load

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── 태그 → 한국어/영어 설명 매핑 ────────────────────────────────────────────

_TEMPO_DESC = {
    "slow":         ("느린 템포", "slow tempo relaxed calm"),
    "medium-tempo": ("중간 템포", "medium tempo moderate pace"),
    "fast":         ("빠른 템포", "fast tempo upbeat energetic"),
}

_TIMBRE_DESC = {
    "dark-timbre":   ("어두운 음색", "dark timbre low frequency gloomy heavy serious"),
    "warm-timbre":   ("따뜻한 음색", "warm timbre natural pleasant comfortable"),
    "bright-timbre": ("밝은 음색", "bright timbre high frequency clear crisp cheerful"),
}

_TEXTURE_DESC = {
    "melodic":  ("선율적", "melodic harmonic instrumental beautiful"),
    "rhythmic": ("리드미컬", "rhythmic percussive driving beat groove"),
}

_ENERGY_DESC = {
    "quiet": ("조용한", "quiet soft subtle minimal"),
    "loud":  ("강렬한", "loud powerful intense bold"),
    "noisy": ("노이즈", "noisy distorted rough"),
}

_DUR_DESC = {
    "short-clip":  ("짧은 클립", "short clip brief sting"),
    "long-track":  ("긴 트랙", "long track extended"),
}

_STYLE_HINTS = [
    # (tempo, timbre, texture) → style hint
    (("fast",),         ("bright-timbre",),   ("rhythmic",),   "upbeat dance pop background music"),
    (("fast",),         ("dark-timbre",),      ("rhythmic",),   "intense dramatic action music"),
    (("fast",),         ("warm-timbre",),      ("melodic",),    "lively cheerful background music"),
    (("medium-tempo",), ("warm-timbre",),      ("melodic",),    "gentle emotional background music"),
    (("medium-tempo",), ("dark-timbre",),      ("melodic",),    "cinematic orchestral background music"),
    (("slow",),         ("warm-timbre",),      ("melodic",),    "calm relaxing piano background music"),
    (("slow",),         ("dark-timbre",),      None,            "dark ambient mysterious background music"),
    (("slow",),         ("warm-timbre",),      None,            "soft soothing background music"),
    (("fast",),         ("bright-timbre",),    ("melodic",),    "bright upbeat melodic background music"),
]


def _style_hint(tags: list[str]) -> str:
    tag_set = set(tags)
    for tempos, timbres, textures, hint in _STYLE_HINTS:
        if not any(t in tag_set for t in tempos):
            continue
        if timbres and not any(t in tag_set for t in timbres):
            continue
        if textures and not any(t in tag_set for t in textures):
            continue
        return hint
    return "background music"


def generate_description(filename: str, tags: list[str], params: dict) -> str:
    """librosa 태그+파라미터 → 자연어 설명 (English + 한국어)."""
    parts_en: list[str] = []
    parts_ko: list[str] = []

    # 스타일 힌트 (첫 번째로 추가 — CLAP 에 가장 중요)
    style = _style_hint(tags)
    parts_en.append(style)

    # 템포
    for tag, (ko, en) in _TEMPO_DESC.items():
        if tag in tags:
            parts_en.append(en)
            parts_ko.append(ko)
            bpm = params.get("tempo_bpm", 0)
            if bpm > 0:
                parts_en.append(f"{bpm:.0f} BPM")
            break

    # 음색
    for tag, (ko, en) in _TIMBRE_DESC.items():
        if tag in tags:
            parts_en.append(en)
            parts_ko.append(ko)
            break

    # 텍스처
    for tag, (ko, en) in _TEXTURE_DESC.items():
        if tag in tags:
            parts_en.append(en)
            parts_ko.append(ko)
            break

    # 에너지
    for tag, (ko, en) in _ENERGY_DESC.items():
        if tag in tags:
            parts_en.append(en)
            parts_ko.append(ko)
            break

    # 길이
    for tag, (ko, en) in _DUR_DESC.items():
        if tag in tags:
            parts_en.append(en)
            parts_ko.append(ko)
            break

    en_desc = " ".join(parts_en)
    ko_desc = " ".join(parts_ko) + " 배경음악" if parts_ko else "배경음악"

    return f"{en_desc} | {ko_desc}"


def build_text_index() -> None:
    """312 트랙 → 텍스트 설명 생성 → CLAP 텍스트 인코딩 → FAISS 인덱스."""
    t0 = time.time()

    # 메타 로드
    meta_path = bgm_config.META_PATH
    meta_raw  = json.loads(meta_path.read_text(encoding="utf-8"))
    items: list[dict] = meta_raw if isinstance(meta_raw, list) else meta_raw.get("items", [])

    # librosa_features 로드 (태그/파라미터 보완용)
    feat_path = bgm_config.INDEX_DIR / "librosa_features.json"
    feat_map: dict[str, dict] = {}
    if feat_path.exists():
        for f in json.loads(feat_path.read_text(encoding="utf-8")):
            feat_map[f["filename"]] = f

    logger.info(f"트랙 수: {len(items)}")

    # CLAP 로드
    logger.info("CLAP 텍스트 인코더 로드 중...")
    clap_load()

    descriptions: list[str] = []
    ids: list[str] = []
    updated_items: list[dict] = []

    for m in items:
        fn   = m.get("filename", "")
        feat = feat_map.get(fn, {})
        tags = feat.get("tags") or m.get("tags") or []
        params = feat.get("params") or m.get("params") or {}

        desc = generate_description(fn, tags, params)
        descriptions.append(desc)
        ids.append(fn)

        # audio_meta.json 에 description 필드 추가
        m["description"] = desc
        # 태그가 없으면 feat에서 보완
        if not m.get("tags") and tags:
            m["tags"] = tags
        updated_items.append(m)

    # CLAP 텍스트 인코딩 (배치)
    logger.info(f"CLAP 텍스트 인코딩 중... ({len(descriptions)} 트랙)")
    BATCH = 32
    all_vecs: list[np.ndarray] = []
    for i in range(0, len(descriptions), BATCH):
        batch = descriptions[i:i+BATCH]
        vecs = encode_text(batch)                 # (B, 512) already L2-norm
        all_vecs.append(vecs)
        if (i // BATCH) % 5 == 0:
            logger.info(f"  {i+len(batch)}/{len(descriptions)}")

    emb = np.vstack(all_vecs).astype(np.float32)
    logger.info(f"임베딩 shape: {emb.shape}")

    # FAISS 인덱스 저장
    import faiss
    idx_dir = bgm_config.INDEX_DIR
    faiss_path = idx_dir / "text_index.faiss"
    emb_path   = idx_dir / "text_emb.npy"
    ids_path   = idx_dir / "text_ids.json"

    faiss_idx = faiss.IndexFlatIP(emb.shape[1])
    faiss_idx.add(emb)
    faiss.write_index(faiss_idx, str(faiss_path))
    np.save(str(emb_path), emb)
    ids_path.write_text(json.dumps({"ids": ids}, ensure_ascii=False), encoding="utf-8")

    logger.info(f"FAISS 텍스트 인덱스 저장: {faiss_path} ({faiss_idx.ntotal} 벡터)")

    # audio_meta.json 백업 후 업데이트
    import shutil, datetime
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    bak = meta_path.with_suffix(f".json.bak.{ts}")
    shutil.copy2(meta_path, bak)
    meta_path.write_text(json.dumps(updated_items, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"audio_meta.json 업데이트 완료 (백업: {bak.name})")

    logger.info(f"총 소요: {time.time()-t0:.1f}s")

    # 샘플 출력
    logger.info("\n=== 샘플 설명 ===")
    for fn, desc in list(zip(ids, descriptions))[:5]:
        logger.info(f"  {fn}: {desc}")


if __name__ == "__main__":
    build_text_index()
