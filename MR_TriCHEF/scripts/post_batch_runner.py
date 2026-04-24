"""post_batch_runner.py — 배치 6 완료 후 순차 실행 통합 스크립트.

배치 6(훤_youtube_2차 전체) 완료 후 아래 작업을 자동으로 순차 실행:
  1. 훤_youtube_1차 레지스트리 수정 + 재인덱싱 (5개)
  2. Music Re 축 SigLIP2 전환 재인덱싱 (14개 음원)
  3. MR_TriCHEF calibration 재측정 (Movie + Music)
  4. PDF body text 2단계 임베딩 (build_doc_body_im --embed-only, 선택)

실행:
    python MR_TriCHEF/scripts/post_batch_runner.py
    python MR_TriCHEF/scripts/post_batch_runner.py --skip-pdf   # PDF 임베딩 건너뜀
    python MR_TriCHEF/scripts/post_batch_runner.py --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
SCRIPTS = _root / "MR_TriCHEF" / "scripts"


def run_step(label: str, script: Path, extra_args: list[str] | None = None,
             dry_run: bool = False) -> bool:
    """스크립트 실행. 성공 시 True, 실패 시 False."""
    args = [sys.executable, str(script)] + (extra_args or [])
    print(f"\n{'='*60}")
    print(f"[Step] {label}")
    print(f"  명령: {' '.join(str(a) for a in args)}")
    print(f"{'='*60}")

    if dry_run:
        print("  [dry-run] 실행 생략")
        return True

    t0 = time.time()
    ret = subprocess.run(args, cwd=str(_root), env={**__import__('os').environ,
                                                     "PYTHONIOENCODING": "utf-8"})
    elapsed = round(time.time() - t0, 1)
    if ret.returncode == 0:
        print(f"  [완료] {elapsed}s")
        return True
    else:
        print(f"  [오류] returncode={ret.returncode}  {elapsed}s")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-pdf", action="store_true",
                        help="PDF body text 임베딩 단계 건너뜀")
    parser.add_argument("--skip-music", action="store_true",
                        help="Music 재인덱싱 건너뜀")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("Post-Batch-6 통합 실행 러너")
    print("=" * 60)

    steps: list[tuple[str, Path, list[str] | None]] = []

    # Step 1: 훤_youtube_1차 레지스트리 수정 + 재인덱싱
    steps.append(("훤_youtube_1차 재인덱싱 (5개)",
                  SCRIPTS / "fix_1cha_registry.py", None))

    # Step 2: Music Re SigLIP2 재인덱싱
    if not args.skip_music:
        steps.append(("Music Re SigLIP2 전환 재인덱싱 (14개 음원)",
                      SCRIPTS / "reindex_music_siglip2.py", None))

    # Step 3: MR_TriCHEF calibration 재측정
    # calibration.py 는 패키지 상대 import → 직접 실행 불가. wrapper 사용.
    cal_script = SCRIPTS / "run_calibration.py"
    steps.append(("MR_TriCHEF Movie+Music calibration 재측정",
                  cal_script, None))

    # Step 4: PDF body text 임베딩
    if not args.skip_pdf:
        steps.append(("PDF body text 2단계 BGE-M3 임베딩 (34,170페이지)",
                      SCRIPTS / "build_doc_body_im.py",
                      ["--embed-only", "--batch", "64"]))

    results: list[tuple[str, bool]] = []
    for label, script, extra in steps:
        ok = run_step(label, script, extra, dry_run=args.dry_run)
        results.append((label, ok))
        if not ok and not args.dry_run:
            print(f"\n[경고] '{label}' 실패. 계속 진행합니다.")

    print(f"\n{'='*60}")
    print("전체 결과:")
    for label, ok in results:
        status = "완료" if ok else "실패"
        print(f"  [{status}] {label}")
    print("=" * 60)

    if all(ok for _, ok in results):
        print("\n모든 작업 완료.")
        print("다음 단계: App/backend 서버 재시작 후 검색 테스트")
    else:
        print("\n일부 실패 — 위 오류 메시지 확인 필요")


if __name__ == "__main__":
    sys.exit(main())
