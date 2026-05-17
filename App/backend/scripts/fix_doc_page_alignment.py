"""[P5] Doc 도메인 6개 캐시 1행 desync 복구.

상태:
  ids/Re/Im/Z      : 34,719 (정렬 기준 후보 A)
  Im_body/sparse/asf_token_sets: 34,718 (정렬 기준 후보 B, 1행 부족)

원인 추정: 마지막 페이지 (요약본 cover p0000.jpg) 가 메인 임베딩(Re/Im/Z) 은
받았지만 body/lexical 후처리가 중단되어 보조 캐시에 누락.

조치: 마지막 1개 페이지를 ids/Re/Im/Z 에서 트림 → 6개 캐시 모두 34,718 정렬
효과: engine 의 body fusion / sparse / ASF 채널 재활성화

위험: 1 페이지 손실 — 그러나 cover 페이지로 검색 가치 낮음
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp

DOC = Path(__file__).resolve().parents[3] / "Data" / "embedded_DB" / "Doc"


def main():
    ts = int(time.time())
    print(f"=== Doc 캐시 정렬 복구 (ts={ts}) ===")

    # 로드
    ids_path = DOC / "doc_page_ids.json"
    raw = json.loads(ids_path.read_text(encoding="utf-8"))
    ids = raw.get("ids", []) if isinstance(raw, dict) else list(raw)
    target_n = len(ids) - 1  # 1행 트림 후 목표 길이

    Re = np.load(DOC / "cache_doc_page_Re.npy")
    Im = np.load(DOC / "cache_doc_page_Im.npy")
    Z = np.load(DOC / "cache_doc_page_Z.npy")
    Im_body = np.load(DOC / "cache_doc_page_Im_body.npy")
    sparse = sp.load_npz(DOC / "cache_doc_page_sparse.npz")
    asf = json.loads((DOC / "asf_token_sets.json").read_text(encoding="utf-8"))

    print(f"  현재: ids={len(ids)} Re={Re.shape[0]} Im={Im.shape[0]} Z={Z.shape[0]} "
          f"Im_body={Im_body.shape[0]} sparse={sparse.shape[0]} asf={len(asf)}")
    print(f"  목표: 모두 {target_n} 로 정렬")
    print(f"  트림 대상 (ids 마지막): {ids[-1]!r}")

    # 검증: Im_body/sparse/asf 가 이미 34718 (= target_n) 인지
    if Im_body.shape[0] != target_n or sparse.shape[0] != target_n or len(asf) != target_n:
        print(f"  [error] 보조 캐시가 {target_n} 이 아님 — 단순 트림 불가, 중단")
        return

    # 백업
    bk = f".pre_align_{ts}"
    for fn in ["doc_page_ids.json", "cache_doc_page_Re.npy",
               "cache_doc_page_Im.npy", "cache_doc_page_Z.npy"]:
        src = DOC / fn
        dst = src.with_suffix(src.suffix + bk)
        shutil.copy2(src, dst)
        print(f"  백업: {fn} → {dst.name}")

    # 트림 후 저장 (tmp + atomic move)
    def _atomic_replace(target: Path, fn):
        tmp = target.with_suffix(target.suffix + f".tmp.{ts}")
        fn(tmp)
        # np.save 가 .npy 보정하는 경우 대응
        if not tmp.exists() and tmp.with_suffix(tmp.suffix + ".npy").exists():
            tmp.with_suffix(tmp.suffix + ".npy").rename(tmp)
        if target.exists():
            target.unlink()
        shutil.move(tmp, target)

    # ids
    _atomic_replace(
        ids_path,
        lambda p: p.write_text(
            json.dumps({"ids": ids[:target_n]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        ),
    )
    # .npy 3개
    for nm, arr in [("cache_doc_page_Re.npy", Re),
                    ("cache_doc_page_Im.npy", Im),
                    ("cache_doc_page_Z.npy", Z)]:
        _atomic_replace(DOC / nm, lambda p, a=arr: np.save(p, a[:target_n]))

    # 결과 확인
    new_ids = json.loads(ids_path.read_text(encoding="utf-8"))
    new_ids = new_ids.get("ids", []) if isinstance(new_ids, dict) else list(new_ids)
    Re2 = np.load(DOC / "cache_doc_page_Re.npy", mmap_mode="r")
    Im2 = np.load(DOC / "cache_doc_page_Im.npy", mmap_mode="r")
    Z2 = np.load(DOC / "cache_doc_page_Z.npy", mmap_mode="r")
    Im_body2 = np.load(DOC / "cache_doc_page_Im_body.npy", mmap_mode="r")
    sparse2 = sp.load_npz(DOC / "cache_doc_page_sparse.npz")
    asf2 = json.loads((DOC / "asf_token_sets.json").read_text(encoding="utf-8"))

    print()
    print(f"  결과: ids={len(new_ids)} Re={Re2.shape[0]} Im={Im2.shape[0]} Z={Z2.shape[0]} "
          f"Im_body={Im_body2.shape[0]} sparse={sparse2.shape[0]} asf={len(asf2)}")
    all_n = {len(new_ids), Re2.shape[0], Im2.shape[0], Z2.shape[0],
             Im_body2.shape[0], sparse2.shape[0], len(asf2)}
    if len(all_n) == 1:
        print(f"  ✓ 모든 캐시 {all_n.pop()} 로 정렬됨 — body/sparse/ASF 채널 재활성화 가능")
    else:
        print(f"  ✗ 정렬 실패: {all_n}")

    print(f"\n후속 작업: 앱 재시작 또는 routes.trichef.reload_engine() 호출")
    print(f"백업 (필요시 복원): *{bk}")


if __name__ == "__main__":
    main()
