"""scripts/run_calibration_strengthen_v3.py — calibration 표본 강화 v3.

목표: 도메인별 relevant Beta 학습 표본 ≥30 확보 → calibration 부실 해소.

  1. match_min 완화 (image 0.07, audio 0.25, doc 0.55, bgm 0.45, video 0.50)
  2. 쿼리 풀 확장 (도메인별 60+개)
  3. Beta + Gaussian 재학습 → calibration_v3.json
  4. 분리도 검증 — 정상 쿼리 vs 무관 쿼리 평균 cosine 비교
  5. v3_summary.md 생성

⚠️ calibration.json 원본 보존. v3 파일로만 저장 → 검토 후 사용자가 직접 적용.

사용:
  cd App/backend
  python scripts/run_calibration_strengthen_v3.py
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = _BACKEND_DIR / "scripts"
sys.path.insert(0, str(_BACKEND_DIR))

API = "http://127.0.0.1:5001/api/search"
HEALTH = "http://127.0.0.1:5001/api/health"


# ─── Flask 관리 ──────────────────────────────────────────────────────────────
def kill_flask():
    try:
        subprocess.run(["powershell", "-Command",
                        "Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                       check=False, capture_output=True)
        time.sleep(2)
    except Exception:
        pass


def start_flask_bg():
    env = os.environ.copy()
    env["TRICHEF_USE_RERANKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
    subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(_BACKEND_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def wait_flask_ready(timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(HEALTH, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def search(query, top_k=50, file_type="image"):
    q = urllib.parse.quote(query)
    url = f"{API}?q={q}&top_k={top_k}&type={file_type}"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


def ensure_flask():
    if wait_flask_ready(timeout=5):
        return
    kill_flask(); start_flask_bg()
    if not wait_flask_ready():
        logger.error("Flask 기동 실패"); sys.exit(1)


# ─── 도메인별 확장 쿼리 풀 ───────────────────────────────────────────────────
RELEVANT_QUERIES = {
    "image": [
        # 동물
        "고양이", "강아지", "토끼", "기린", "말", "닭", "새", "물고기", "곰", "여우",
        "사자", "코끼리", "원숭이", "판다", "돼지", "양", "오리", "거북이",
        # 음식
        "햄버거", "피자", "초밥", "케이크", "떡볶이", "파스타", "샐러드", "스테이크",
        "라면", "김밥", "치킨", "빵", "커피", "와인",
        # 사물·교통
        "자동차", "비행기", "자전거", "선박", "기차", "오토바이", "버스",
        # 자연
        "산", "바다", "강", "꽃", "노을", "구름", "눈", "비", "벚꽃", "단풍",
        # 사람·활동
        "운동하는 사람", "공부하는 학생", "요리사", "의사", "교사", "아기",
        # 장소·풍경
        "도시 야경", "공원", "박물관", "교회", "사원", "해변", "숲", "사막",
        # 복합
        "박스 안 고양이", "노을 지는 해변", "벚꽃 거리", "눈 덮인 산",
        # 영문
        "cat", "dog", "modern building", "vintage car", "sunset beach",
        "kitten", "puppy", "flower", "mountain", "ocean",
    ],
    "audio": [
        "고양이 모시고", "박춘봉 초밥", "AI 인공지능", "GPT OpenAI", "AI 검사 수사",
        "주식 투자", "코스피", "부동산", "다스뵈이다", "철학자", "윤석열",
        "자율주행", "딥페이크", "유튜브", "한예종", "정치 뉴스", "검찰 개혁",
        "엔비디아", "테슬라", "암호화폐", "비트코인", "메타버스",
        "인플레이션", "금리", "선거", "국회", "법원",
        "출산율", "인구", "기후 변화", "원전",
    ],
    "doc": [
        "AI 인공지능", "주식 투자", "부동산", "환경 정책", "교육 개혁",
        "범죄 데이터", "농촌 토지", "자전거길", "공간 데이터", "보고서",
        "기술 발전", "코스피", "GDP", "에너지", "원전",
        "환경 보호", "탄소 중립", "재생 에너지", "전기차",
        "고령화", "출산율", "복지", "의료", "보건",
        "교통", "도시 계획", "주거 정책",
    ],
    "bgm": [
        "잔잔한 음악", "신나는 비트", "슬픈 발라드", "긴장감 있는 음악", "몽환적 음악",
        "재즈 피아노", "록 기타", "클래식 음악", "EDM", "힙합", "발라드",
        "기타 솔로", "피아노 연주", "드럼 비트", "바이올린", "색소폰",
        "빠른 템포", "느린 음악", "중간 템포",
        "영화 OST", "운동 음악", "카페 음악", "잘 때 듣는 음악", "공부할 때 듣는 음악",
        "soft jazz", "fast rock", "ambient electronic", "chill lofi", "dramatic orchestral",
        "acoustic guitar", "upbeat pop",
        "여름 해변에서 듣는 음악", "비 오는 날 카페", "겨울 밤 재즈",
    ],
    "video": [
        "고양이", "강아지", "요리", "운동", "여행", "음악", "춤", "게임", "뉴스",
        "영화 예고편", "드라마 명장면", "유튜브 인터뷰", "토크쇼",
        "AI 인공지능", "리뷰", "튜토리얼", "강의", "다큐멘터리",
        "스포츠 하이라이트", "공연 실황", "공식 뮤직비디오",
    ],
}

# 무관 쿼리 — 분리도 검증용
IRRELEVANT_QUERIES = {
    "image": ["팝송", "보이저호", "양자컴퓨터", "추상 개념", "외계인", "MZ세대", "인플레이션"],
    "audio": ["고양이", "햄버거", "벚꽃", "팝송", "보이저호", "외계인"],
    "doc":   ["고양이", "햄버거", "벚꽃", "팝송", "보이저호"],
    "bgm":   ["고양이", "AI 인공지능", "주식 투자", "보이저호", "햄버거", "벚꽃"],
    "video": ["팝송", "보이저호", "양자컴퓨터"],
}

# 도메인별 매칭 임계값 (완화된 v3)
MATCH_THRESHOLDS = {
    "image": ("visual_match", 0.0, 0.07),   # rerank_min, match_min
    "audio": ("audio_match",  0.5, 0.25),
    "doc":   ("dense",        0.0, 0.55),
    "bgm":   ("dense",        0.0, 0.45),
    "video": ("dense",        0.0, 0.50),
}


# ─── 분포 학습 ───────────────────────────────────────────────────────────────
def fit_distribution(samples: list[float]) -> dict | None:
    if len(samples) < 5:
        return None
    try:
        import numpy as np
        from scipy.stats import beta as beta_dist
        arr = np.asarray(samples, dtype=np.float64)
        s_min, s_max = float(arr.min()), float(arr.max())
        span = s_max - s_min
        if span < 1e-6:
            return None
        normalized = np.clip((arr - s_min) / span, 1e-4, 1 - 1e-4)
        a, b, _, _ = beta_dist.fit(normalized, floc=0, fscale=1)
        return {
            "n_samples": len(samples),
            "gaussian": {"mu": round(float(arr.mean()), 4),
                         "sigma": round(float(arr.std()), 4)},
            "beta": {"a": round(float(a), 4), "b": round(float(b), 4),
                     "loc": round(s_min, 4), "scale": round(span, 4)},
        }
    except Exception as e:
        logger.warning(f"  fit 실패: {e}")
        return None


def collect_cosines(domain: str, queries: list[str]) -> list[float]:
    match_field, rerank_min, match_min = MATCH_THRESHOLDS[domain]
    cosines = []
    for i, q in enumerate(queries, 1):
        try:
            results = search(q, top_k=50, file_type=domain)
        except Exception as e:
            logger.warning(f"  [{domain}] '{q}' 실패: {e}")
            continue
        for r in results:
            rs = r.get("rerank_score")
            mv = r.get(match_field) or r.get("dense")
            if rs is None or mv is None:
                continue
            if float(rs) >= rerank_min and float(mv) >= match_min:
                cosines.append(float(mv))
        if i % 10 == 0:
            logger.info(f"  [{domain}] {i}/{len(queries)} 진행, 누적 n={len(cosines)}")
    return cosines


# ─── 분리도 측정 ─────────────────────────────────────────────────────────────
def measure_separation(domain: str) -> dict:
    """정상 vs 무관 쿼리 top-3 평균 cosine 비교 — 분리도 지표."""
    match_field, _, _ = MATCH_THRESHOLDS[domain]
    rel_top = []
    irr_top = []
    for q in RELEVANT_QUERIES.get(domain, [])[:20]:
        try:
            res = search(q, top_k=3, file_type=domain)
            for r in res:
                v = r.get(match_field) or r.get("dense")
                if v is not None:
                    rel_top.append(float(v))
        except Exception:
            pass
    for q in IRRELEVANT_QUERIES.get(domain, []):
        try:
            res = search(q, top_k=3, file_type=domain)
            for r in res:
                v = r.get(match_field) or r.get("dense")
                if v is not None:
                    irr_top.append(float(v))
        except Exception:
            pass
    try:
        import numpy as np
        rel_arr = np.asarray(rel_top) if rel_top else np.asarray([0])
        irr_arr = np.asarray(irr_top) if irr_top else np.asarray([0])
        return {
            "relevant": {"n": len(rel_top), "mean": round(float(rel_arr.mean()), 4),
                         "min": round(float(rel_arr.min()), 4) if rel_top else None,
                         "max": round(float(rel_arr.max()), 4) if rel_top else None},
            "irrelevant": {"n": len(irr_top), "mean": round(float(irr_arr.mean()), 4),
                           "min": round(float(irr_arr.min()), 4) if irr_top else None,
                           "max": round(float(irr_arr.max()), 4) if irr_top else None},
            "separation": round(float(rel_arr.mean() - irr_arr.mean()), 4) if rel_top and irr_top else None,
        }
    except Exception:
        return {"relevant_n": len(rel_top), "irrelevant_n": len(irr_top)}


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    logger.info("═" * 60)
    logger.info("Calibration v3 표본 강화 시작")
    logger.info("═" * 60)
    t0 = time.time()
    ensure_flask()

    # 기존 calibration 로드 (irrelevant 보존)
    cal_path = _BACKEND_DIR / "services" / "calibration.json"
    cal_orig = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else {}

    cal_v3 = {}
    separation_report = {}

    for domain in ["image", "audio", "doc", "bgm", "video"]:
        logger.info(f"\n══ [{domain}] relevant 표본 수집 ══")
        queries = RELEVANT_QUERIES.get(domain, [])
        cosines = collect_cosines(domain, queries)
        logger.info(f"  → 누적 n={len(cosines)}")

        relevant_dist = fit_distribution(cosines)
        if relevant_dist:
            logger.info(f"  Beta a={relevant_dist['beta']['a']}, b={relevant_dist['beta']['b']}, "
                        f"μ={relevant_dist['gaussian']['mu']}, σ={relevant_dist['gaussian']['sigma']}")
        else:
            logger.warning(f"  [{domain}] 표본 부족 또는 분포 학습 실패")

        # irrelevant 는 기존 보존 (별도 noise 측정 필요 없음 — 이전 phase 로 충분)
        irr = (cal_orig.get(domain) or {}).get("irrelevant") or {}
        cal_v3[domain] = {
            "relevant": relevant_dist,
            "irrelevant": irr or None,
        }

        # 분리도 측정
        logger.info(f"  분리도 측정 중...")
        sep = measure_separation(domain)
        separation_report[domain] = sep
        rel_m = sep.get("relevant", {}).get("mean")
        irr_m = sep.get("irrelevant", {}).get("mean")
        sep_v = sep.get("separation")
        logger.info(f"  분리도: relevant μ={rel_m}, irrelevant μ={irr_m}, Δ={sep_v}")

    # 저장
    out_v3 = SCRIPTS_DIR / "calibration_v3.json"
    out_v3.write_text(json.dumps(cal_v3, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"\n→ {out_v3}")

    sep_path = SCRIPTS_DIR / "calibration_separation_v3.json"
    sep_path.write_text(json.dumps(separation_report, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    logger.info(f"→ {sep_path}")

    # 요약 마크다운
    md = ["# Calibration v3 — 표본 강화 결과\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n",
          "## 도메인별 relevant 표본\n\n",
          "| 도메인 | n | target | 충족 | μ | σ | Beta a | Beta b |\n",
          "|---|---|---|---|---|---|---|---|\n"]
    targets = {"image": 30, "audio": 30, "doc": 30, "bgm": 30, "video": 20}
    for dom, dist in cal_v3.items():
        rel = dist.get("relevant") or {}
        n = rel.get("n_samples", 0)
        g = rel.get("gaussian", {})
        b = rel.get("beta", {})
        target = targets.get(dom, 30)
        ok = "✓" if n >= target else "✗"
        md.append(f"| {dom} | {n} | {target} | {ok} | "
                  f"{g.get('mu', '-')} | {g.get('sigma', '-')} | "
                  f"{b.get('a', '-')} | {b.get('b', '-')} |\n")

    md.append("\n## 분리도 (정상 top-3 평균 vs 무관 top-3 평균)\n\n")
    md.append("| 도메인 | 정상 μ | 무관 μ | Δ (정상-무관) |\n")
    md.append("|---|---|---|---|\n")
    for dom, sep in separation_report.items():
        rm = sep.get("relevant", {}).get("mean", "-")
        im = sep.get("irrelevant", {}).get("mean", "-")
        d = sep.get("separation", "-")
        md.append(f"| {dom} | {rm} | {im} | {d} |\n")

    md.append("\n## 다음 단계\n\n")
    md.append("1. `calibration_v3.json` 검토\n")
    md.append("2. 만족 시 `services/calibration.json` 으로 복사 (사용자 명시 승인)\n")
    md.append("3. Bayesian (image) / floor (audio) 재계산 효과 측정\n")

    md_path = SCRIPTS_DIR / "calibration_v3_summary.md"
    md_path.write_text("".join(md), encoding="utf-8")
    logger.info(f"→ {md_path}")

    logger.info("═" * 60)
    logger.info(f"완료 — 소요 {(time.time() - t0)/60:.1f}분")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
