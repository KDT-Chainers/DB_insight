"""BGM 도메인 확장 — Movie/Rec audio 라이브러리 통합 인덱싱.

추가 인덱스 대상:
  raw_DB/Movie/<* != 정혜_BGM_1차>/*.mp4|mkv|webm|m4v
  raw_DB/Rec/**/*.wav|mp3|m4a

각 파일:
  - file-level: 0~60s 1개 CLAP embedding → BGM file-level index 추가
  - segment-level: 60s window, 60s hop (영상 길어도 sampling 적게) → segment index 추가
  - Chromaprint fingerprint 계산 → fp DB 추가
  - audio_meta.json 에 source="movie_lib" or "rec_lib" 표시

산출:
  Data/embedded_DB/Bgm/audio_meta.json (확장)
  Data/embedded_DB/Bgm/clap_emb.npy (확장)
  Data/embedded_DB/Bgm/clap_index.faiss (재빌드)
  Data/embedded_DB/Bgm/cache_seg_emb.npy (확장)
  Data/embedded_DB/Bgm/cache_seg_index.json (확장)
  Data/embedded_DB/Bgm/cache_seg_faiss.faiss (재빌드)
  Data/embedded_DB/Bgm/chromaprint_db.json (확장)

기본 GPU 사용 (CLAP cuda).
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

# GPU 우선 (Qwen 종료 후이므로 안전)
os.environ.pop("FORCE_CPU", None)
os.environ["OMC_DISABLE_QWEN_PREWARM"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


SEG_WINDOW = 60.0   # 60s 윈도우
SEG_HOP    = 60.0   # 60s hop (오버랩 0)
MAX_SEG_PER_FILE = 5    # 영상 너무 길어도 최대 5 segment (5분 sampling)


def collect_extra_files() -> list[dict]:
    """Movie (정혜 제외) + Rec 의 audio 파일 수집."""
    out = []
    raw_movie = ROOT / "Data" / "raw_DB" / "Movie"
    if raw_movie.is_dir():
        for sub in raw_movie.iterdir():
            if sub.is_dir() and sub.name != "정혜_BGM_1차":
                for ext in ("*.mp4", "*.mkv", "*.webm", "*.m4v"):
                    for p in sub.rglob(ext):
                        if p.is_file():
                            out.append({"path": p, "source": "movie_lib"})
    raw_rec = ROOT / "Data" / "raw_DB" / "Rec"
    if raw_rec.is_dir():
        for ext in ("*.wav", "*.mp3", "*.m4a", "*.flac"):
            for p in raw_rec.rglob(ext):
                if p.is_file():
                    out.append({"path": p, "source": "rec_lib"})
    return out


def main():
    print("=== BGM 라이브러리 확장 인덱싱 시작 ===", flush=True)
    print(f"  GPU: {os.environ.get('FORCE_CPU', 'cuda 사용')}", flush=True)
    t0 = time.time()

    import numpy as np
    from services.bgm import (
        bgm_config, audio_extract, chromaprint as cp,
        clap_encoder, index_store, segments as bgm_seg,
        librosa_features, filename_parse,
    )

    # 1. 기존 인덱스 로드
    meta_store = index_store.MetaStore(bgm_config.META_PATH)
    existing_items = meta_store.all()
    existing_filenames = {it.get("filename") for it in existing_items}
    print(f"  기존 카탈로그: {len(existing_items)} entries", flush=True)

    # 2. 새 파일 수집
    extras = collect_extra_files()
    new_extras = [e for e in extras if e["path"].name not in existing_filenames]
    print(f"  Movie/Rec 라이브러리: {len(extras)} files (신규 {len(new_extras)})", flush=True)

    if not new_extras:
        print("  처리할 신규 파일 없음 — 종료", flush=True)
        return 0

    # 3. 파일별 처리
    new_meta_items: list[dict] = list(existing_items)  # working copy
    fp_db = cp.load_db(bgm_config.CHROMAPRINT_DB)

    # CLAP file-level embeddings
    existing_emb = np.load(bgm_config.CLAP_EMB_PATH) if bgm_config.CLAP_EMB_PATH.is_file() else None
    file_emb_list: list[np.ndarray] = list(existing_emb) if existing_emb is not None else []

    # Segment embeddings (기존)
    existing_seg_emb = None
    if bgm_seg.SEG_EMB_PATH.is_file():
        existing_seg_emb = np.load(bgm_seg.SEG_EMB_PATH)
    existing_seg_idx = []
    if bgm_seg.SEG_INDEX_PATH.is_file():
        existing_seg_idx = json.loads(bgm_seg.SEG_INDEX_PATH.read_text(encoding="utf-8"))

    seg_emb_list: list[np.ndarray] = list(existing_seg_emb) if existing_seg_emb is not None else []
    seg_idx_list: list[dict] = list(existing_seg_idx)

    print(f"\n  처리 시작 (~{len(new_extras)*1.5:.0f}s 예상)...", flush=True)

    for i, entry in enumerate(new_extras, 1):
        src = entry["path"]
        source_kind = entry["source"]
        try:
            # ① mp4/wav → wav 추출 (CLAP 48kHz, 최대 5분)
            wav48 = bgm_config.AUDIO_CACHE_DIR / (src.stem + ".wav")
            if not wav48.is_file():
                audio_extract.extract_wav(
                    src, wav48,
                    sample_rate=bgm_config.CLAP_SR,
                    duration=300.0,  # 최대 5분
                    overwrite=False,
                )

            # ② Chromaprint
            fp_pair = cp.fingerprint_file(src)
            if fp_pair is not None:
                fp_db[src.name] = {
                    "fingerprint": fp_pair[0],
                    "duration":    fp_pair[1],
                }

            # ③ CLAP file-level 임베딩 (60s)
            try:
                emb = clap_encoder.encode_audio_file(wav48, max_seconds=60.0)
                file_emb_list.append(emb)
            except Exception as ex:
                print(f"    [{i}] CLAP file-level 실패 {src.name}: {ex}", flush=True)
                continue

            # ④ CLAP segment-level 임베딩 (최대 5 segments)
            try:
                y, sr = audio_extract.load_wav(wav48, sr=bgm_config.CLAP_SR, max_seconds=300.0)
                dur = len(y) / sr
                ranges = bgm_seg.segment_ranges(dur, window=SEG_WINDOW, hop=SEG_HOP)
                ranges = ranges[:MAX_SEG_PER_FILE]   # 최대 N개 sampling
                if ranges:
                    seg_audio = bgm_seg._segment_audio(y, sr, ranges)
                    seg_embs = clap_encoder.encode_audio(seg_audio)
                    file_idx = len(new_meta_items)  # 곧 추가될 meta 의 인덱스
                    for si, ((s, e), emb_s) in enumerate(zip(ranges, seg_embs)):
                        seg_emb_list.append(emb_s)
                        seg_idx_list.append({
                            "file_idx": file_idx,
                            "seg_idx":  si,
                            "filename": src.name,
                            "start":    float(s),
                            "end":      float(e),
                        })
            except Exception as ex:
                print(f"    [{i}] segment 실패 {src.name}: {ex}", flush=True)

            # ⑤ librosa 특징
            try:
                y22, sr22 = audio_extract.load_wav(wav48, sr=22050, max_seconds=60.0)
                flat, _ = librosa_features.compute_features(y22, sr22)
                tags = librosa_features.features_to_tags(flat)
            except Exception:
                flat, tags = {}, []

            # ⑥ meta 추가
            ga, gt = filename_parse.guess_artist_title(src.name)
            new_meta_items.append({
                "filename":      src.name,
                "path":          str(src.resolve()),
                "guess_artist":  ga,
                "guess_title":   gt,
                "duration":      float(fp_pair[1]) if fp_pair else flat.get("duration_sec", 0.0),
                "acr_artist":    "",
                "acr_title":     "",
                "acr_synced_at": None,
                "tags":          tags,
                "params":        flat,
                "source":        source_kind,        # ← 신규 필드: catalog | movie_lib | rec_lib
            })

            if i % 20 == 0 or i == len(new_extras):
                elapsed = time.time() - t0
                eta = elapsed / i * (len(new_extras) - i)
                print(f"    [{i:3d}/{len(new_extras)}] {src.name[:40]:<40} elapsed={elapsed:.0f}s eta={eta:.0f}s",
                      flush=True)
        except Exception as ex:
            print(f"    [{i}] 전체 실패 {src.name}: {ex}", flush=True)

    # 7. 기존 catalog 항목에 source 필드 추가 (없으면 'catalog')
    for it in new_meta_items[:len(existing_items)]:
        it.setdefault("source", "catalog")

    # 8. 저장
    print("\n  인덱스 저장 중...", flush=True)
    meta_store.replace_all(new_meta_items)

    file_emb_arr = np.stack(file_emb_list, axis=0) if file_emb_list else np.zeros((0, bgm_config.CLAP_DIM), dtype=np.float32)
    np.save(bgm_config.CLAP_EMB_PATH, file_emb_arr)
    file_idx = index_store.build_index(file_emb_arr)
    index_store.save_index(file_idx, bgm_config.CLAP_INDEX_PATH)
    print(f"    file-level: {file_emb_arr.shape}", flush=True)

    if seg_emb_list:
        seg_emb_arr = np.stack(seg_emb_list, axis=0)
        np.save(bgm_seg.SEG_EMB_PATH, seg_emb_arr)
        bgm_seg.SEG_INDEX_PATH.write_text(
            json.dumps(seg_idx_list, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        seg_idx = index_store.build_index(seg_emb_arr)
        index_store.save_index(seg_idx, bgm_seg.SEG_FAISS_PATH)
        print(f"    segment:    {seg_emb_arr.shape}", flush=True)

    cp.save_db(bgm_config.CHROMAPRINT_DB, fp_db)
    print(f"    chromaprint: {len(fp_db)} entries", flush=True)

    elapsed = time.time() - t0
    print(f"\n=== 완료 ({elapsed:.0f}s) ===", flush=True)
    print(f"  total meta:     {len(new_meta_items)}", flush=True)
    print(f"  catalog:        {sum(1 for it in new_meta_items if it.get('source') == 'catalog')}", flush=True)
    print(f"  movie_lib:      {sum(1 for it in new_meta_items if it.get('source') == 'movie_lib')}", flush=True)
    print(f"  rec_lib:        {sum(1 for it in new_meta_items if it.get('source') == 'rec_lib')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
