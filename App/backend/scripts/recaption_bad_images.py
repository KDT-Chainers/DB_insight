"""[P2] 품질 미달 이미지 캡션 재생성 스크립트.

대상: Data/embedded_DB/Img/_recaption_candidates.json 에 나열된 키들
  - 챗봇 붕괴 마커 포함
  - 중국어 우세 (>10%)
  - 한국어 부족 (<10%, 20자+)

동작:
  1) 각 후보 키의 staged 경로 또는 abs_aliases 원본 경로를 찾음
  2) 캡션 파일 (.caption.json, .txt, .qwen) 삭제 → 강제 재생성
  3) registry 엔트리 제거 → embed_image_file 의 SHA-skip 우회
  4) captions_triple.jsonl 의 해당 라인 제거
  5) embed_image_file 호출 → 새 가드레일 적용된 Qwen-VL 캡션 + 3축 재임베딩
  6) replace_by_file 이 자동으로 .npy / img_ids.json 정합 유지

사용:
  python App/backend/scripts/recaption_bad_images.py            # 전체 실행
  python App/backend/scripts/recaption_bad_images.py --limit 3  # 처음 3건만
  python App/backend/scripts/recaption_bad_images.py --dry-run  # 시뮬레이션
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 경로 설정 — 스크립트가 어디서 실행되든 App/backend 를 sys.path 에 추가
_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))

from config import PATHS  # noqa: E402
from embedders.trichef.incremental_runner import embed_image_file  # noqa: E402


def _load_candidates() -> list[str]:
    p = Path(PATHS["TRICHEF_IMG_CACHE"]) / "_recaption_candidates.json"
    if not p.exists():
        print(f"[error] 후보 파일 없음: {p}")
        print("        먼저 진단 스크립트로 _recaption_candidates.json 을 생성하세요.")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def _resolve_image_path(key: str) -> Path | None:
    """registry key 로부터 실제 디스크 상의 이미지 경로 찾기.

    우선순위: staged 경로 → abs_aliases → raw_DB/Img/<key>
    """
    img_cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    reg = json.loads((img_cache / "registry.json").read_text(encoding="utf-8"))
    ent = reg.get(key)
    if isinstance(ent, dict):
        # 1) staged 경로
        st = ent.get("staged")
        if st and Path(st).is_file():
            return Path(st)
        # 2) abs_aliases (원본 경로)
        for alias in (ent.get("abs_aliases") or []):
            if alias and Path(alias).is_file():
                return Path(alias)
    # 3) raw_DB/Img/<key> 폴백
    raw_dir = Path(PATHS["RAW_DB"]) / "Img"
    cand = raw_dir / key
    return cand if cand.is_file() else None


def _purge_caption_artifacts(key: str) -> list[str]:
    """기존 캡션 파일·registry·captions_triple.jsonl 항목 제거."""
    img_cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    stem = Path(key).stem
    removed = []

    # 1) 캡션 파일
    for ext in (".caption.json", ".txt", ".qwen"):
        f = cap_dir / f"{stem}{ext}"
        if f.exists():
            f.unlink()
            removed.append(str(f.name))

    # 2) captions_triple.jsonl 라인 제거
    jsonl = img_cache / "captions_triple.jsonl"
    if jsonl.exists():
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        new = [
            ln for ln in lines
            if f'"{key}"' not in ln and f'"{stem}"' not in ln
        ]
        if len(new) != len(lines):
            jsonl.write_text(
                "\n".join(new) + ("\n" if new else ""),
                encoding="utf-8",
            )
            removed.append(f"captions_triple.jsonl(-{len(lines)-len(new)})")

    # 3) registry 엔트리 — 부분 삭제 (caption 재생성을 위해 SHA-skip 우회)
    #    embed_image_file 가 자동으로 새 entry 를 쓰므로 단순 delete 면 충분
    reg_path = img_cache / "registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    if key in reg:
        del reg[key]
        reg_path.write_text(
            json.dumps(reg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        removed.append("registry")

    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="처리할 최대 건수 (0=전체)")
    ap.add_argument("--dry-run", action="store_true",
                    help="실제 변경 없이 후보만 출력")
    ap.add_argument("--start", type=int, default=0,
                    help="후보 리스트 시작 인덱스 (이어 받기)")
    args = ap.parse_args()

    candidates = _load_candidates()
    total = len(candidates)
    print(f"=== 재캡션 대상: 총 {total}건 ===")
    if args.start:
        candidates = candidates[args.start:]
        print(f"    start={args.start} → 남은 {len(candidates)}건")
    if args.limit > 0:
        candidates = candidates[:args.limit]
        print(f"    limit={args.limit} → {len(candidates)}건 처리")
    if args.dry_run:
        print("[dry-run] 변경 없이 후보 10건 미리보기:")
        for i, k in enumerate(candidates[:10]):
            p = _resolve_image_path(k)
            mark = "✓" if p else "✗ 경로 없음"
            print(f"  [{i+1}] {mark} {k}  ->  {p}")
        return

    ok = err = skip = 0
    t0 = time.time()
    for i, key in enumerate(candidates, 1):
        img_path = _resolve_image_path(key)
        if not img_path:
            print(f"[{i:>5d}/{len(candidates)}] SKIP key={key}: 디스크에 파일 없음")
            skip += 1
            continue

        # 정리
        try:
            removed = _purge_caption_artifacts(key)
        except Exception as e:
            print(f"[{i:>5d}/{len(candidates)}] PURGE FAIL {key}: {e}")
            err += 1
            continue

        # 재임베딩
        try:
            res = embed_image_file(str(img_path), defer_lexical_rebuild=True)
            st = res.get("status", "?")
            elapsed = time.time() - t0
            avg = elapsed / max(i, 1)
            eta_min = avg * (len(candidates) - i) / 60
            print(f"[{i:>5d}/{len(candidates)}] {st:<7s} {img_path.name[:50]:<50s} "
                  f"avg={avg:.1f}s ETA={eta_min:.0f}m purged={removed}")
            if st == "done":
                ok += 1
            else:
                err += 1
        except Exception as e:
            print(f"[{i:>5d}/{len(candidates)}] EMBED FAIL {img_path.name}: {type(e).__name__}: {e}")
            err += 1

    # 일괄 종료 후 lexical rebuild 1회 + engine reload
    print("\n=== 후처리 (lexical rebuild + engine reload) ===")
    try:
        from services.trichef import lexical_rebuild as _lex
        _lex.rebuild_image_lexical()
        print("  ✓ image lexical 재구축")
    except Exception as e:
        print(f"  ✗ lexical rebuild 실패: {e}")
    try:
        from routes.trichef import reload_engine
        reload_engine()
        print("  ✓ engine reload")
    except Exception as e:
        print(f"  ✗ engine reload 실패: {e}")

    print(f"\n=== 완료: 성공 {ok} / 실패 {err} / 건너뜀 {skip} "
          f"(총 {time.time()-t0:.0f}초) ===")


if __name__ == "__main__":
    main()
