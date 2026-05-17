"""[권장 후속 작업 #1] 짧은 doc 페이지 검색 노이즈 페널티.

배경:
  진단 결과, <200자 doc 페이지가 검색 top10 을 자주 점유:
    - "AI 인공지능" → top10 의 60% 가 짧은 페이지 (대부분 표지/간지)
    - "경주 동궁 월지" → top10 의 70%
    - "자기소개서 취업" → top10 의 40%
  원인: 짧은 텍스트는 토큰 농도가 높아 cosine sim 이 인위적으로 상승.
        표지·간지·섹션 시작 페이지가 실제 정보 가치는 낮은데 점수 우위.

설계:
  - 인덱싱 시점에 page_text/<stem>/p####.txt 길이를 미리 캐시
    (cache_doc_page_text_lens.json) — 검색 시 O(1) 조회
  - 검색 결과에 sigmoid-style 페널티 적용:
        penalty = min(1.0, text_len / 200) ^ 0.5
        score_adjusted = score * (0.5 + 0.5 * penalty)
    → text_len=0   : score × 0.50  (-50%)
       text_len=50 : score × 0.75
       text_len=200: score × 1.00  (불변)
       text_len=500: score × 1.00  (불변)

적용 (수동 통합):
  1) build_text_length_cache() 1회 실행 → JSON 생성
  2) search.py 의 _sort_key() 끝부분에 _short_page_penalty(r) 곱셈 추가
  3) bench_search_quality.py 로 회귀 검증

위험:
  - 진짜 짧지만 정확한 페이지(예: 한 문장 답)도 감점됨
  - 임계 200자 / α=0.5 는 휴리스틱 — 도메인별 튜닝 필요할 수 있음

미적용 사유: 회귀 위험 — 사용자 검토 후 결정.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def _doc_extract_dir() -> Path:
    sys.path.insert(0, str(_ROOT / "App" / "backend"))
    from config import PATHS
    return Path(PATHS["TRICHEF_DOC_EXTRACT"])


def _doc_cache_dir() -> Path:
    sys.path.insert(0, str(_ROOT / "App" / "backend"))
    from config import PATHS
    return Path(PATHS["TRICHEF_DOC_CACHE"])


# ── 캐시 빌드 (1회 실행) ────────────────────────────────────────────────
def build_text_length_cache(out_name: str = "cache_doc_page_text_lens.json") -> int:
    """page_text 디렉토리를 순회하며 각 페이지 텍스트 길이를 측정 → JSON 저장.

    Returns: 저장된 항목 수
    """
    pt_root = _doc_extract_dir() / "page_text"
    out_path = _doc_cache_dir() / out_name
    if not pt_root.exists():
        raise FileNotFoundError(f"page_text 디렉토리 없음: {pt_root}")

    lens: dict[str, int] = {}
    for f in pt_root.rglob("*.txt"):
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # rel_key 추정 (검색 엔진의 id 와 일치하도록)
        # id 포맷: page_images/<stem>/p####.<ext>
        stem = f.parent.name
        pid = f.stem  # "p0042"
        # 확장자별로 다중 등록 (실제 인덱스는 .jpg/.png 등)
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            rel_key = f"page_images/{stem}/{pid}{ext}"
            lens[rel_key] = len(t)
    out_path.write_text(
        json.dumps(lens, ensure_ascii=False),
        encoding="utf-8",
    )
    return len(lens)


# ── 런타임 조회 (검색 시 사용) ──────────────────────────────────────────
_LEN_CACHE: dict[str, int] | None = None
_LEN_CACHE_MTIME: float = -1.0


def _load_len_cache() -> dict[str, int]:
    """mtime 기반 lazy reload."""
    global _LEN_CACHE, _LEN_CACHE_MTIME
    p = _doc_cache_dir() / "cache_doc_page_text_lens.json"
    if not p.exists():
        return {}
    mtime = p.stat().st_mtime
    if _LEN_CACHE is None or mtime != _LEN_CACHE_MTIME:
        try:
            _LEN_CACHE = json.loads(p.read_text(encoding="utf-8"))
            _LEN_CACHE_MTIME = mtime
        except Exception:
            _LEN_CACHE = {}
    return _LEN_CACHE


def short_page_penalty(
    result_id: str,
    *,
    floor_chars: int = 200,
    min_multiplier: float = 0.5,
    exponent: float = 0.5,
) -> float:
    """검색 결과에 적용할 페널티 multiplier 반환.

    Args:
        result_id: 검색 결과의 id (e.g., "page_images/<stem>/p0042.jpg")
        floor_chars: 이 값 이상이면 페널티 없음 (multiplier = 1.0)
        min_multiplier: 최저 multiplier (text_len=0 일 때)
        exponent: 곡선 모양 — 0.5 면 sqrt, 1.0 이면 선형

    Returns:
        multiplier ∈ [min_multiplier, 1.0]
    """
    cache = _load_len_cache()
    text_len = cache.get(result_id)
    if text_len is None:
        return 1.0  # 캐시 없으면 페널티 미적용
    if text_len >= floor_chars:
        return 1.0
    ratio = (text_len / floor_chars) ** exponent
    return min_multiplier + (1.0 - min_multiplier) * ratio


# ── search.py 통합 예시 (수동 적용) ─────────────────────────────────────
INTEGRATION_PATCH = """
# search.py 의 _sort_key() 내부, primary 계산 후 마지막에 추가:

    # [권장] 짧은 페이지 노이즈 페널티 (doc_page 전용)
    if r.get("file_type") == "doc":
        try:
            from services.short_page_penalty import short_page_penalty
            primary *= short_page_penalty(r.get("id", ""))
        except Exception:
            pass
"""


if __name__ == "__main__":
    # 캐시 빌드 모드
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="텍스트 길이 캐시 생성")
    ap.add_argument("--test", action="store_true", help="페널티 함수 테스트")
    args = ap.parse_args()

    if args.build:
        n = build_text_length_cache()
        print(f"✓ cache_doc_page_text_lens.json 저장: {n}개 항목")

    if args.test:
        print("\n페널티 함수 단위 테스트:")
        cases = [
            (0,    0.50),  # 빈 페이지
            (50,   0.75),
            (100,  0.85),
            (150,  0.93),
            (200,  1.00),  # floor
            (500,  1.00),
            (1000, 1.00),
        ]
        for tlen, expected in cases:
            # 가짜 캐시 주입
            globals()["_LEN_CACHE"] = {"test_id": tlen}
            globals()["_LEN_CACHE_MTIME"] = 999
            p = short_page_penalty("test_id")
            ok = "✓" if abs(p - expected) < 0.05 else "✗"
            print(f"  {ok} text_len={tlen:>5d} → multiplier={p:.3f} (예상 {expected:.2f})")
