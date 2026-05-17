"""[Whisper 환각 정리] 동영상 segment의 명백한 STT 환각 제거.

식별 기준:
  1) 매우 짧은 segment (<1초) + 긴 텍스트(20자+) — 음성 불가능
  2) 동일 텍스트 5회 이상 반복 (Whisper "재생성 루프" 환각)
  3) 시간 인접 segment에 동일 텍스트 반복 (보이저 5:31~5:34 케이스)

조치:
  - 식별된 segment를 segments.json 에서 제거
  - movie_ids.json + cache_movie_{Re,Im,Z}.npy + sparse.npz + token_sets 동기 정리
  - lexical rebuild 필요 (별도 후처리)

백업: 모든 파일 .pre_hallucin_<ts> 로 보존
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from collections import Counter

import numpy as np
import scipy.sparse as sp

MV = Path(__file__).resolve().parents[3] / "Data" / "embedded_DB" / "Movie"


def _text(s: dict) -> str:
    return (s.get("stt_text") or s.get("text") or s.get("caption") or "").strip()


def _duration(s: dict) -> float:
    return float(s.get("t_end", 0) - s.get("t_start", 0))


def main():
    ts = int(time.time())
    print(f"=== Whisper 환각 segment 정리 (ts={ts}) ===")

    segs = json.loads((MV / "segments.json").read_text(encoding="utf-8"))
    n0 = len(segs)
    print(f"  현재 segments: {n0}건")

    # 1) 동일 텍스트 N회 반복 카운트
    text_count = Counter(_text(s) for s in segs)

    # 2) 인접 같은 텍스트 (5:31~5:34 케이스) 식별
    # 같은 파일 + 직전 segment 와 동일 텍스트 + 시간 차 < 5초
    adjacent_dup = set()
    prev_by_file: dict[str, dict] = {}
    for i, s in enumerate(segs):
        f = s.get("file", "")
        t = _text(s)
        if not t:
            continue
        prev = prev_by_file.get(f)
        if prev and _text(prev) == t:
            gap = s.get("t_start", 0) - prev.get("t_end", 0)
            if gap < 5.0:
                adjacent_dup.add(i)
        prev_by_file[f] = s

    # 3) keep_mask 생성
    keep = np.ones(n0, dtype=bool)
    drop_reasons = Counter()

    for i, s in enumerate(segs):
        t = _text(s)
        dur = _duration(s)
        if not t:
            continue  # 이미 빈 텍스트는 P1 cleanup 으로 제거됐어야 함 (남았으면 유지)

        # 기준 1: 매우 짧음 + 긴 텍스트
        if dur < 1.0 and len(t) >= 20:
            keep[i] = False
            drop_reasons["short_with_long_text"] += 1
            continue
        # 추가 1.5: 매우 짧음 + 텍스트 있음 (0.5초 미만)
        if dur < 0.5 and len(t) >= 10:
            keep[i] = False
            drop_reasons["very_short_with_text"] += 1
            continue

        # 기준 2: 동일 텍스트 5회 이상 반복
        if text_count[t] >= 5:
            keep[i] = False
            drop_reasons["repeated_text"] += 1
            continue

        # 기준 3: 인접 같은 텍스트
        if i in adjacent_dup:
            keep[i] = False
            drop_reasons["adjacent_duplicate"] += 1
            continue

    n_drop = int((~keep).sum())
    n_keep = int(keep.sum())
    print(f"\n  제거 대상: {n_drop}건 ({n_drop/n0*100:.1f}%)")
    for reason, cnt in drop_reasons.most_common():
        print(f"    {reason:<28s} {cnt:>6d}건")
    print(f"  유지: {n_keep}건")

    if n_drop == 0:
        print("  제거 대상 없음 — 종료")
        return

    # 4) 정합 검증
    ids_path = MV / "movie_ids.json"
    raw = json.loads(ids_path.read_text(encoding="utf-8"))
    ids = raw.get("ids", []) if isinstance(raw, dict) else list(raw)
    if len(ids) != n0:
        print(f"  [error] ids {len(ids)} ≠ segments {n0} — 중단")
        sys.exit(1)

    npy_paths = {
        "Re": MV / "cache_movie_Re.npy",
        "Im": MV / "cache_movie_Im.npy",
        "Z":  MV / "cache_movie_Z.npy",
    }
    arrays = {k: np.load(p) for k, p in npy_paths.items()}
    sparse_path = MV / "cache_movie_sparse.npz"
    sparse = sp.load_npz(sparse_path)
    tokens_path = MV / "movie_token_sets.json"
    tokens = json.loads(tokens_path.read_text(encoding="utf-8"))

    for k, a in arrays.items():
        if a.shape[0] != n0:
            print(f"  [error] {k} shape {a.shape[0]} ≠ segments {n0} — 중단")
            sys.exit(1)
    if sparse.shape[0] != n0:
        print(f"  [error] sparse {sparse.shape[0]} ≠ segments {n0} — 중단")
        sys.exit(1)
    if len(tokens) != n0:
        print(f"  [error] tokens {len(tokens)} ≠ segments {n0} — 중단")
        sys.exit(1)

    # 5) 백업
    bk = f".pre_hallucin_{ts}"
    for p in [MV/"segments.json", ids_path, sparse_path, tokens_path, *npy_paths.values()]:
        shutil.copy2(p, p.with_suffix(p.suffix + bk))
    print(f"\n  백업 완료 ({bk})")

    # 6) 정리된 데이터 생성
    new_segs = [s for s, k in zip(segs, keep) if k]
    new_ids = [i for i, k in zip(ids, keep) if k]
    new_arrays = {k: arr[keep] for k, arr in arrays.items()}
    keep_idx = np.where(keep)[0]
    new_sparse = sparse[keep_idx]
    new_tokens = [tokens[i] for i in keep_idx.tolist()]

    # 7) 저장 (atomic tmp + move)
    def _atomic(target: Path, fn):
        tmp = target.with_suffix(target.suffix + f".tmp.{ts}")
        fn(tmp)
        # np.save / sp.save_npz 가 자동 확장자(.npy / .npz) 추가하는 경우 보정
        for auto_ext in (".npy", ".npz"):
            auto_tmp = tmp.with_suffix(tmp.suffix + auto_ext)
            if not tmp.exists() and auto_tmp.exists():
                auto_tmp.rename(tmp)
                break
        if not tmp.exists():
            raise FileNotFoundError(f"tmp file not created: {tmp}")
        if target.exists():
            target.unlink()
        shutil.move(tmp, target)

    _atomic(MV/"segments.json",
            lambda p: p.write_text(json.dumps(new_segs, ensure_ascii=False), encoding="utf-8"))
    _atomic(ids_path,
            lambda p: p.write_text(json.dumps({"ids": new_ids}, ensure_ascii=False, indent=2), encoding="utf-8"))
    for k, target in npy_paths.items():
        _atomic(target, lambda p, a=new_arrays[k]: np.save(p, a))
    _atomic(sparse_path, lambda p: sp.save_npz(p, new_sparse))
    _atomic(tokens_path,
            lambda p: p.write_text(json.dumps(new_tokens, ensure_ascii=False), encoding="utf-8"))

    # 8) 결과 검증
    print(f"\n  결과:")
    final_segs = json.loads((MV/"segments.json").read_text(encoding="utf-8"))
    final_ids = json.loads(ids_path.read_text(encoding="utf-8")).get("ids", [])
    print(f"    segments.json: {n0} → {len(final_segs)}")
    print(f"    movie_ids.json: {n0} → {len(final_ids)}")
    for k, p in npy_paths.items():
        shape = np.load(p, mmap_mode="r").shape
        print(f"    {p.name}: → {shape}")
    print(f"    sparse: → {sp.load_npz(sparse_path).shape}")
    print(f"    tokens: → {len(json.loads(tokens_path.read_text(encoding='utf-8')))}")

    print(f"\n=== 완료 — 환각 segment {n_drop}건 제거 ===")
    print(f"백업: *{bk}")
    print("\n후속: 앱 재시작 또는 reload_engine() — 검색 캐시 갱신")


if __name__ == "__main__":
    main()
