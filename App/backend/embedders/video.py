"""
동영상 임베더 (MP4, AVI, MOV, MKV, WMV) — M11 방식
spec_video.md 기준 구현

파이프라인:
  Step 1-A. BLIP 캡셔닝  (매 30프레임 → 영어 캡션, 이미지 파일 저장 없음)
  Step 1-B. Whisper STT  (medium, 한국어)
  Step 2.   동적 가중치  (n_frames / (n_frames + stt_len) 비율 → 9분위 버킷)
  Step 3.   양방향 청킹  (BLIP: 10개씩, STT: 400자/100자 오버랩)
  Step 4.   e5-large 임베딩 1024d  ("passage: " 접두사 필수)
            → ChromaDB "files_video" 컬렉션
            → chunk_source = "blip" | "stt" 로 구분 저장

캐시 (extracted_DB):
  {stem}_captions.json   ← BLIP 캡션 list[str]
  {stem}_stt.txt         ← Whisper STT 원문
  {stem}_blip_embs.npy   ← BLIP 청크 임베딩 (N×1024)
  {stem}_blip_chunks.json
  {stem}_stt_embs.npy    ← STT 청크 임베딩 (M×1024)
  {stem}_stt_chunks.json
  weight_buckets.json    ← 영상별 동적 가중치 (전체 공유)

검색:
  "query: {쿼리}" → e5 1024d
  영상별 BLIP청크 max유사도(blip_score) + STT청크 max유사도(stt_score)
  최종 = blip_weight × blip_score + stt_weight × stt_score
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import numpy as np
from pathlib import Path

from _extensions import VID_EXTS as _VID_EXTS
SUPPORTED_EXTENSIONS = set(_VID_EXTS)

# ── 설정값 (spec 고정) ────────────────────────────────────────────
FRAME_INTERVAL    = 30
BLIP_GROUP_SIZE   = 10
STT_CHUNK_SIZE    = 400
STT_CHUNK_OVERLAP = 100
E5_MODEL_NAME     = "intfloat/multilingual-e5-large"
BLIP_MODEL_NAME   = "Salesforce/blip-image-captioning-base"
WHISPER_MODEL     = "medium"

BUCKET_WEIGHTS = [
    (0.10, 0.90), (0.20, 0.80), (0.30, 0.70),
    (0.40, 0.60), (0.50, 0.50), (0.60, 0.40),
    (0.70, 0.30), (0.80, 0.20), (0.90, 0.10),
]

# ── 캐시 경로 ─────────────────────────────────────────────────────
# extracted_DB/Movie/ : 텍스트 캐시 (캡션 JSON, STT txt, 청크 JSON, 가중치)
# embedded_DB/Movie/  : 임베딩 캐시 (.npy) + ChromaDB
from config import EXTRACTED_DB_VIDEO as EXTRACTED_DB
from config import EMBEDDED_DB_VIDEO  as EMBEDDING_CACHE

WEIGHT_BUCKETS_PATH = EXTRACTED_DB / "weight_buckets.json"


def _cache_stem(file_path: str) -> str:
    h    = hashlib.md5(file_path.encode()).hexdigest()[:12]
    name = Path(file_path).stem
    return f"{name}_{h}"


# ── 모델 지연 로딩 ────────────────────────────────────────────────
_blip_proc  = None
_blip_model = None
_whisper    = None
_e5         = None


def _get_blip():
    global _blip_proc, _blip_model
    if _blip_model is None:
        import torch
        from transformers import BlipProcessor, BlipForConditionalGeneration
        _blip_proc  = BlipProcessor.from_pretrained(BLIP_MODEL_NAME)
        _blip_model = BlipForConditionalGeneration.from_pretrained(BLIP_MODEL_NAME)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _blip_model = _blip_model.to(device).eval()
    return _blip_proc, _blip_model


def _get_whisper():
    global _whisper
    if _whisper is None:
        import torch
        from faster_whisper import WhisperModel
        device  = "cuda" if torch.cuda.is_available() else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        _whisper = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
    return _whisper


def _get_e5():
    global _e5
    if _e5 is None:
        from sentence_transformers import SentenceTransformer
        _e5 = SentenceTransformer(E5_MODEL_NAME)
    return _e5


# ── Step 1-A: BLIP 캡셔닝 ─────────────────────────────────────────

def _get_captions(file_path: str) -> list[str]:
    """
    매 30프레임마다 BLIP 영어 캡션 1개 생성.
    이미지 파일은 저장하지 않고 캡션 텍스트만 저장.
    캐시({stem}_captions.json) 있으면 재사용.
    """
    stem  = _cache_stem(file_path)
    cache = EXTRACTED_DB / f"{stem}_captions.json"

    if cache.exists():
        data = json.loads(cache.read_text("utf-8"))
        if not data:
            return []
        # 기존 캐시가 list[dict] 형식일 경우 텍스트만 추출
        if isinstance(data[0], dict):
            return [d.get("caption", "") for d in data if d.get("caption")]
        return [c for c in data if c]

    import cv2
    import torch
    from PIL import Image

    proc, model = _get_blip()
    device = next(model.parameters()).device

    cap    = cv2.VideoCapture(file_path)
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_indices = list(range(0, total, FRAME_INTERVAL))
    captions = []

    for idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        inputs  = proc(images=pil_img, return_tensors="pt").to(device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=50)
        captions.append(proc.decode(out[0], skip_special_tokens=True))
        # pil_img, frame 여기서 소멸 — 이미지 파일 저장 없음

    cap.release()
    cache.write_text(json.dumps(captions, ensure_ascii=False), encoding="utf-8")
    return captions


# ── Step 1-B: Whisper STT ─────────────────────────────────────────

def _get_stt(file_path: str) -> str:
    """
    Whisper medium 한국어 STT.
    캐시({stem}_stt.txt) 있으면 재사용.
    """
    stem  = _cache_stem(file_path)
    cache = EXTRACTED_DB / f"{stem}_stt.txt"

    if cache.exists():
        return cache.read_text("utf-8").strip()

    whisper = _get_whisper()
    segments, _ = whisper.transcribe(
        file_path, language="ko", beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    text = " ".join(s.text.strip() for s in segments).strip() or "(음성 없음)"
    cache.write_text(text, encoding="utf-8")
    return text


# ── Step 2: 동적 가중치 ───────────────────────────────────────────

def _compute_weight(n_frames: int, stt_len: int) -> tuple[float, float]:
    """
    단일 영상의 raw_ratio → 9분위 버킷 → (blip_weight, stt_weight).
    ratio = n_frames / (n_frames + stt_len)
    비율을 0~8 구간에 선형 매핑.
    """
    total = n_frames + stt_len
    ratio = n_frames / total if total > 0 else 0.5
    # 0.0 ~ 1.0 → 0 ~ 8 구간
    idx = min(int(ratio * 9), 8)
    return BUCKET_WEIGHTS[idx]


def _load_weight_buckets() -> dict:
    if WEIGHT_BUCKETS_PATH.exists():
        return json.loads(WEIGHT_BUCKETS_PATH.read_text("utf-8"))
    return {}


def _save_weight_bucket(stem: str, blip_w: float, stt_w: float) -> None:
    buckets = _load_weight_buckets()
    buckets[stem] = {"blip_weight": blip_w, "stt_weight": stt_w}
    WEIGHT_BUCKETS_PATH.write_text(
        json.dumps(buckets, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Step 3: 양방향 청킹 ───────────────────────────────────────────

def _chunk_text_fwd(text: str) -> list[str]:
    chunks, start = [], 0
    step = STT_CHUNK_SIZE - STT_CHUNK_OVERLAP
    while start < len(text):
        chunks.append(text[start:start + STT_CHUNK_SIZE])
        start += step
    return chunks or [text]


def _chunk_text_bwd(text: str) -> list[str]:
    return [c[::-1] for c in _chunk_text_fwd(text[::-1])]


def _chunk_captions_fwd(captions: list[str]) -> list[str]:
    result = []
    for i in range(0, len(captions), BLIP_GROUP_SIZE):
        result.append(". ".join(captions[i:i + BLIP_GROUP_SIZE]))
    return result or [""]


def _chunk_captions_bwd(captions: list[str]) -> list[str]:
    return _chunk_captions_fwd(list(reversed(captions)))


# ── Step 4: e5 임베딩 ─────────────────────────────────────────────

def _embed_passages(texts: list[str]) -> np.ndarray:
    """
    텍스트 청크 → 1024d 벡터.
    e5 규칙: 저장 시 "passage: " 접두사 필수.
    """
    e5 = _get_e5()
    prefixed = [f"passage: {t}" for t in texts]
    return e5.encode(
        prefixed,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 20,
    ).astype(np.float32)


def _load_or_embed(stem: str, chunks: list[str], kind: str) -> np.ndarray:
    """
    kind: "blip" | "stt"
    .npy 임베딩 캐시 → embedded_DB/Movie/
    청크 JSON 텍스트 캐시 → extracted_DB/Movie/
    """
    emb_path   = EMBEDDING_CACHE / f"{stem}_{kind}_embs.npy"   # 임베딩 벡터
    chunk_path = EXTRACTED_DB    / f"{stem}_{kind}_chunks.json" # 청크 텍스트

    # 이전 경로(extracted_DB)에 있으면 새 경로로 이동
    old_emb = EXTRACTED_DB / f"{stem}_{kind}_embs.npy"
    if old_emb.exists() and not emb_path.exists():
        old_emb.rename(emb_path)

    if emb_path.exists() and chunk_path.exists():
        return np.load(str(emb_path)), json.loads(chunk_path.read_text("utf-8"))

    vecs = _embed_passages(chunks)
    np.save(str(emb_path), vecs)
    chunk_path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    return vecs, chunks


# ── 진입점 ────────────────────────────────────────────────────────

EMBED_STEPS = [
    (1, 4, "프레임 캡셔닝 중..."),   # BLIP
    (2, 4, "음성 텍스트 변환 중..."), # Whisper STT
    (3, 4, "임베딩 생성 중..."),      # e5-large
    (4, 4, "벡터DB 저장 중..."),      # ChromaDB
]


def embed(file_path: str, progress_cb=None) -> dict:
    """
    동영상 파일 한 개를 M11 파이프라인으로 임베딩 → ChromaDB 저장.

    progress_cb(step, total, detail) : 단계 진행 콜백 (선택)

    반환:
      {"status": "done",    "chunks": int, "blip": int, "stt": int}
      {"status": "skipped", "reason": str}
      {"status": "error",   "reason": str}
    """
    from db.vector_store import upsert_chunks, delete_file

    def _cb(step_idx: int) -> bool:
        """콜백 호출. True 반환 시 중단 신호."""
        if progress_cb:
            s, t, d = EMBED_STEPS[step_idx]
            return bool(progress_cb(step=s, total=t, detail=d))
        return False

    stem      = _cache_stem(file_path)
    file_name = os.path.basename(file_path)
    fhash     = hashlib.md5(file_path.encode()).hexdigest()[:8]

    # ── Step 1: BLIP 캡셔닝 ──────────────────────────────────────
    if _cb(0): return {"status": "skipped", "reason": "사용자 중단"}
    try:
        captions = _get_captions(file_path)
    except Exception as e:
        return {"status": "error", "reason": f"BLIP 캡셔닝 실패: {e}"}

    if not captions:
        captions = []   # 캡션 없어도 STT로 진행

    # ── Step 2: Whisper STT ──────────────────────────────────────
    if _cb(1): return {"status": "skipped", "reason": "사용자 중단"}
    try:
        stt_text = _get_stt(file_path)
    except Exception as e:
        return {"status": "error", "reason": f"STT 실패: {e}"}

    stt_empty = (not stt_text.strip() or stt_text == "(음성 없음)")
    if not captions and stt_empty:
        return {"status": "skipped", "reason": "캡션도 STT도 없음"}

    # 동적 가중치 + 양방향 청킹
    blip_w, stt_w = _compute_weight(len(captions), len(stt_text))
    _save_weight_bucket(stem, blip_w, stt_w)
    blip_chunks = _chunk_captions_fwd(captions) + _chunk_captions_bwd(captions) if captions else []
    stt_chunks  = _chunk_text_fwd(stt_text)     + _chunk_text_bwd(stt_text)     if not stt_empty else []

    # ── Step 3: e5-large 임베딩 ──────────────────────────────────
    if _cb(2): return {"status": "skipped", "reason": "사용자 중단"}
    try:
        blip_vecs, blip_chunks = _load_or_embed(stem, blip_chunks, "blip") if blip_chunks else (np.array([]), [])
        stt_vecs,  stt_chunks  = _load_or_embed(stem, stt_chunks,  "stt")  if stt_chunks  else (np.array([]), [])
    except Exception as e:
        return {"status": "error", "reason": f"임베딩 실패: {e}"}

    # ── Step 4: ChromaDB 저장 ────────────────────────────────────
    if _cb(3): return {"status": "skipped", "reason": "사용자 중단"}
    try:
        delete_file(file_path, file_type="video")

        all_ids, all_embs, all_metas = [], [], []

        for i, (vec, chunk) in enumerate(zip(blip_vecs.tolist() if len(blip_vecs) else [], blip_chunks)):
            all_ids.append(f"{fhash}_blip_{i}")
            all_embs.append(vec)
            all_metas.append({
                "file_path":    file_path,
                "file_name":    file_name,
                "file_type":    "video",
                "chunk_source": "blip",
                "chunk_index":  i,
                "chunk_text":   chunk[:300],
                "blip_weight":  blip_w,
                "stt_weight":   stt_w,
            })

        for i, (vec, chunk) in enumerate(zip(stt_vecs.tolist() if len(stt_vecs) else [], stt_chunks)):
            all_ids.append(f"{fhash}_stt_{i}")
            all_embs.append(vec)
            all_metas.append({
                "file_path":    file_path,
                "file_name":    file_name,
                "file_type":    "video",
                "chunk_source": "stt",
                "chunk_index":  i,
                "chunk_text":   chunk[:300],
                "blip_weight":  blip_w,
                "stt_weight":   stt_w,
            })

        if not all_ids:
            return {"status": "skipped", "reason": "저장할 청크 없음"}

        upsert_chunks(ids=all_ids, embeddings=all_embs, metadatas=all_metas)

        return {
            "status": "done",
            "chunks": len(all_ids),
            "blip":   len(blip_chunks),
            "stt":    len(stt_chunks),
        }

    except Exception as e:
        return {"status": "error", "reason": f"ChromaDB 저장 실패: {e}"}
