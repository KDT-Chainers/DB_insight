"""scripts/build_av_lexical.py — Movie/Music 초기 sparse/vocab/ASF 인덱스 빌드.

사용법:
    cd App/backend
    python scripts/build_av_lexical.py [--movie] [--music] [--all]

기본값: --all (movie + music 모두 빌드)

빌드 산출물:
    Data/embedded_DB/Movie/cache_movie_sparse.npz  ← 신규
    Data/embedded_DB/Movie/vocab_movie.json         ← 갱신
    Data/embedded_DB/Movie/movie_token_sets.json    ← 갱신
    Data/embedded_DB/Rec/cache_music_sparse.npz    ← 신규
    Data/embedded_DB/Rec/vocab_music.json           ← 갱신
    Data/embedded_DB/Rec/music_token_sets.json      ← 갱신

완료 후 백엔드 재시작(또는 /api/trichef/reload)으로 엔진이 인덱스를 로드합니다.
"""
from __future__ import annotations
import sys
import io
import argparse
import logging
import time
from pathlib import Path

# ── sys.path 설정 (backend 루트를 기준으로 실행) ─────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows cp949 환경에서 한글/특수문자 출력 문제 방지
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("build_av_lexical")


def run_movie() -> None:
    logger.info("=== Movie sparse/vocab/ASF 빌드 시작 ===")
    t0 = time.time()
    from services.trichef.lexical_rebuild import rebuild_movie_lexical
    result = rebuild_movie_lexical()
    elapsed = time.time() - t0
    if result.get("skipped"):
        logger.warning(f"Movie 빌드 건너뜀: {result.get('reason')}")
    else:
        logger.info(
            f"Movie 빌드 완료 ({elapsed:.1f}s): "
            f"vocab={result.get('vocab')}, "
            f"sparse={result.get('sparse')}, "
            f"nnz={result.get('nnz')}"
        )


def run_music() -> None:
    logger.info("=== Music sparse/vocab/ASF 빌드 시작 ===")
    t0 = time.time()
    from services.trichef.lexical_rebuild import rebuild_music_lexical
    result = rebuild_music_lexical()
    elapsed = time.time() - t0
    if result.get("skipped"):
        logger.warning(f"Music 빌드 건너뜀: {result.get('reason')}")
    else:
        logger.info(
            f"Music 빌드 완료 ({elapsed:.1f}s): "
            f"vocab={result.get('vocab')}, "
            f"sparse={result.get('sparse')}, "
            f"nnz={result.get('nnz')}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Movie/Music AV Lexical Index Builder")
    parser.add_argument("--movie", action="store_true", help="Movie만 빌드")
    parser.add_argument("--music", action="store_true", help="Music만 빌드")
    parser.add_argument("--all",   action="store_true", help="Movie + Music 모두 빌드 (기본)")
    args = parser.parse_args()

    do_movie = args.movie or args.all or not (args.movie or args.music)
    do_music = args.music or args.all or not (args.movie or args.music)

    total_t0 = time.time()
    if do_movie:
        run_movie()
    if do_music:
        run_music()

    logger.info(f"=== 전체 완료 ({time.time() - total_t0:.1f}s) ===")
    logger.info("백엔드 재시작 또는 curl -X POST http://localhost:포트/api/trichef/reload 실행")


if __name__ == "__main__":
    main()
