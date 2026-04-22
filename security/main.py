"""
main.py
──────────────────────────────────────────────────────────────────────────────
보안 RAG 시스템 진입점.

실행 방법:
  python main.py              # Gradio UI 실행 (기본)
  python main.py --cli        # CLI 모드 (터미널에서 대화형 실행)
  python main.py --gen-data   # 테스트 더미 데이터 생성
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 로그 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_ui() -> None:
    """Gradio 웹 UI 실행"""
    from ui.gradio_app import main as gradio_main
    logger.info("Gradio UI 시작 → http://localhost:7860")
    gradio_main()


def run_cli() -> None:
    """대화형 CLI 모드"""
    from agents.orchestrator import Orchestrator
    from security.policy import UploadPolicy

    print("\n" + "=" * 60)
    print("   🔐 보안 RAG 시스템 (CLI 모드)")
    print("=" * 60)

    orch = Orchestrator.build()

    while True:
        print("\n[메뉴]")
        print("  1. 파일 업로드")
        print("  2. 질문하기")
        print("  3. 종료")

        choice = input("\n선택 (1/2/3): ").strip()

        if choice == "1":
            file_path = input("파일 경로 (.pdf / .hwpx): ").strip().strip('"')
            if not Path(file_path).exists():
                print("❌ 파일을 찾을 수 없습니다.")
                continue

            print("\n🔍 보안 스캔 중...")
            scan = orch.handle_upload(file_path)

            if scan.error:
                print(f"❌ 오류: {scan.error}")
                continue

            summary = scan.pii_summary
            print(f"\n스캔 완료: {scan.filename}")
            print(f"  총 청크: {summary.get('total_chunks', 0)}")
            print(f"  PII 청크: {summary.get('affected_chunks', 0)}")

            if scan.has_pii:
                print("\n⚠️  개인정보가 발견되었습니다.")
                print("처리 방식:")
                print("  1. 마스킹 후 임베딩")
                print("  2. 민감 청크 제외")
                print("  3. 그대로 임베딩")
                print("  4. 취소")

                sub = input("선택 (1/2/3/4): ").strip()
                policy_map = {
                    "1": UploadPolicy.MASK_AND_EMBED,
                    "2": UploadPolicy.SKIP_PII_CHUNKS,
                    "3": UploadPolicy.EMBED_ALL,
                    "4": UploadPolicy.CANCEL,
                }
                policy_choice = policy_map.get(sub, UploadPolicy.CANCEL)
            else:
                print("\n✅ 개인정보 없음 — 바로 임베딩합니다.")
                policy_choice = UploadPolicy.EMBED_ALL

            result = orch.commit_upload(scan, policy_choice)
            if result["status"] == "cancelled":
                print("🚫 취소되었습니다.")
            else:
                print(f"✅ 임베딩 완료: {result['embedded_chunks']} 청크 저장")

        elif choice == "2":
            query = input("\n질문: ").strip()
            if not query:
                continue

            print("\n🔎 검색 및 분류 중...")
            resp = orch.handle_query(query)

            label_icon = {"NORMAL": "🟢", "SENSITIVE": "🟡", "DANGEROUS": "🔴"}.get(resp.label, "⚪")
            print(f"\n{label_icon} [{resp.label}] {resp.reason}")

            if resp.blocked:
                print(f"\n⛔ {resp.answer}")
            elif resp.masked_preview:
                print(f"\n📋 마스킹 미리보기:\n{resp.answer}")
                full = input("\n전체 내용을 보시겠습니까? (y/n): ").strip().lower()
                if full == "y":
                    resp2 = orch.handle_query(query, full_view=True)
                    print(f"\n📄 전체 답변:\n{resp2.answer}")
            else:
                print(f"\n💬 답변:\n{resp.answer}")

        elif choice == "3":
            print("종료합니다.")
            break
        else:
            print("1, 2, 3 중 선택해주세요.")


def generate_test_data() -> None:
    """테스트 더미 데이터 생성"""
    from tests.dummy_data_generator import generate_all
    generate_all()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="로컬 보안 RAG 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python main.py              # Gradio UI (기본)
  python main.py --cli        # CLI 모드
  python main.py --gen-data   # 더미 데이터 생성
        """,
    )
    parser.add_argument("--cli",      action="store_true", help="CLI 대화형 모드")
    parser.add_argument("--gen-data", action="store_true", help="테스트 더미 데이터 생성")

    args = parser.parse_args()

    if args.gen_data:
        generate_test_data()
    elif args.cli:
        run_cli()
    else:
        run_ui()


if __name__ == "__main__":
    main()
