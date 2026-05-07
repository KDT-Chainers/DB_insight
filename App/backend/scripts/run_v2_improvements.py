"""scripts/run_v2_improvements.py — 4가지 후속 개선 통합 파이프라인.

자동 sequential 실행 (~60~90분):
  1. 캡션 거짓말 재검사 (threshold 0.05 → 0.20) — 진짜 거짓말 발견
  2. n_sigma 분석 알고리즘 개선 — 정상/무관 분리도 정확 측정
  3. Phase 1 calibration 쿼리 풀 확장 (60+ 쿼리, n≥30 목표)
  4. BGM 카테고리 정성 분석 — librosa features 매칭 평가

산출물:
  scripts/real_caption_lies_v2.json (진짜 거짓 캡션 — threshold 0.20)
  scripts/n_sigma_analysis_v2.json (개선 알고리즘 결과)
  scripts/calibration_v2.json (확장된 relevant 분포)
  scripts/bgm_qualitative_v2.json (BGM 카테고리 정성 평가)
  scripts/v2_summary.md (사람 친화 요약)

사용:
  cd App/backend
  python scripts/run_v2_improvements.py
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
from collections import Counter
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = _BACKEND_DIR / "scripts"
sys.path.insert(0, str(_BACKEND_DIR))

API = "http://127.0.0.1:5001/api/search"
HEALTH = "http://127.0.0.1:5001/api/health"


# ─── 공통 유틸 ────────────────────────────────────────────────────────────────
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
    with urllib.request.urlopen(url, timeout=90) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


# ─── Step 1: 캡션 거짓말 재검사 (threshold 0.20) ──────────────────────────────
def step1_caption_lies_v2(threshold: float = 0.20) -> dict:
    logger.info("═" * 60)
    logger.info(f"[1/4] 캡션 거짓말 재검사 (threshold={threshold}, no caption 제외)")
    logger.info("═" * 60)

    try:
        import numpy as np
        from config import PATHS
        from embedders.trichef import siglip2_re

        idir = Path(PATHS["TRICHEF_IMG_CACHE"])
        img_emb = np.load(str(idir / "cache_img_Re_siglip2.npy"))
        norms = np.linalg.norm(img_emb, axis=1, keepdims=True)
        img_emb = (img_emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)
        ids_data = json.loads((idir / "img_ids.json").read_text(encoding="utf-8"))
        ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
        N = len(ids)
        logger.info(f"  이미지: {N}개")

        captions_path = idir / "caption_3stage.json"
        captions = json.loads(captions_path.read_text(encoding="utf-8"))

        # 캡션 있는 이미지만 처리
        items_with_cap = []
        for i, _id in enumerate(ids):
            cap_obj = captions.get(_id, {})
            cap = (cap_obj.get("L1", "") + " " + cap_obj.get("L2", "")
                   + " " + cap_obj.get("L3", "")).strip()
            if cap and len(cap) >= 10:
                items_with_cap.append((i, _id, cap))

        logger.info(f"  캡션 있는 이미지: {len(items_with_cap)}개")

        suspects = []
        batch = 64
        for batch_start in range(0, len(items_with_cap), batch):
            batch_items = items_with_cap[batch_start: batch_start + batch]
            batch_caps = [it[2] for it in batch_items]
            batch_indices = [it[0] for it in batch_items]
            batch_ids = [it[1] for it in batch_items]

            try:
                txt_emb = siglip2_re.embed_texts(batch_caps)
                txt_emb = np.asarray(txt_emb, dtype=np.float32)
                norms2 = np.linalg.norm(txt_emb, axis=1, keepdims=True)
                txt_emb = txt_emb / np.maximum(norms2, 1e-8)
            except Exception:
                continue

            img_batch = img_emb[batch_indices]
            cos = np.einsum("ij,ij->i", img_batch, txt_emb)
            for k, (_id, cap, c) in enumerate(zip(batch_ids, batch_caps, cos)):
                if c < threshold:
                    suspects.append({"id": _id, "caption": cap[:150], "cosine": float(c)})

            if batch_start % 320 == 0:
                logger.info(f"  진행: {batch_start}/{len(items_with_cap)}, 의심 {len(suspects)}건")

        suspects.sort(key=lambda x: x["cosine"])
        logger.info(f"\n  → 진짜 거짓 캡션 (cosine < {threshold}): {len(suspects)}건")

        # 패턴 분석
        if suspects:
            keywords = Counter()
            for s in suspects:
                cap = s["caption"].lower()
                for kw in ["고양이", "강아지", "사람", "음식", "건물", "하늘", "차",
                           "꽃", "동물", "사진", "cat", "dog", "person", "building"]:
                    if kw in cap:
                        keywords[kw] += 1
            logger.info(f"  거짓 캡션 빈출 키워드: {dict(keywords.most_common(10))}")

            logger.info(f"\n  Top 10 (가장 낮은 cosine):")
            for i, s in enumerate(suspects[:10], 1):
                logger.info(f"    {i:2d}. [{s['cosine']:.3f}] {s['id'][:50]}")
                logger.info(f"        캡션: {s['caption'][:100]}")

        # 저장
        out_path = SCRIPTS_DIR / "real_caption_lies_v2.json"
        out_path.write_text(json.dumps({
            "threshold": threshold,
            "n_total_with_captions": len(items_with_cap),
            "n_suspects": len(suspects),
            "keywords": dict(Counter(suspects[0].get("caption", "").lower() for s in suspects[:50] if s).most_common(20)) if suspects else {},
            "suspects": suspects[:300],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"\n  저장: {out_path}")

        return {"n_suspects": len(suspects), "n_total": len(items_with_cap)}
    except Exception as e:
        logger.exception(f"  실패: {e}")
        return {"error": str(e)}


# ─── Step 2: n_sigma 분석 알고리즘 개선 ──────────────────────────────────────
def step2_n_sigma_v2() -> dict:
    """정상/무관 쿼리 명시 → 분리도 (정상 결과 수 × 무관 차단율) 측정."""
    logger.info("═" * 60)
    logger.info("[2/4] n_sigma 분석 알고리즘 개선")
    logger.info("═" * 60)

    report_path = SCRIPTS_DIR / "overnight_report.json"
    if not report_path.exists():
        return {"error": "overnight_report.json missing"}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    sweep = report.get("phase3_n_sigma_sweep", {})

    # 도메인별 정상/무관 쿼리 분류
    RELEVANT = {
        "image": ["고양이", "햄버거", "박스 속에 들어있는 고양이"],
        "audio": ["고양이"],   # 다스뵈이다 episode 매칭
        "doc":   ["AI 인공지능"],
        "bgm":   ["잔잔한 음악"],
    }
    IRRELEVANT = {
        "image": ["팝송", "보이저호"],
        "audio": ["보이저호", "팝송"],
        "doc":   ["보이저호"],
        "bgm":   ["보이저호", "고양이"],
    }

    recommendations = {}
    for domain, n_results in sweep.items():
        scores = {}
        for n_key, queries in n_results.items():
            n_val = float(n_key.replace("n_", ""))
            rel_results = sum(queries.get(q, {}).get("n", 0) for q in RELEVANT.get(domain, []))
            irr_zero = sum(1 for q in IRRELEVANT.get(domain, [])
                            if queries.get(q, {}).get("n", 0) == 0)
            irr_total = max(len(IRRELEVANT.get(domain, [])), 1)
            irr_block_rate = irr_zero / irr_total

            # 분리도 = (정상 결과 수 / 30) × 무관 차단율 (둘 다 정규화)
            rel_norm = min(rel_results / 30, 1.0)
            score = rel_norm * irr_block_rate
            scores[n_val] = {
                "score": round(score, 3),
                "rel_results": rel_results,
                "irr_block_rate": irr_block_rate,
            }

        if scores:
            best_n = max(scores.keys(), key=lambda n: scores[n]["score"])
            recommendations[domain] = {
                "recommended_n": best_n,
                "best_score": scores[best_n]["score"],
                "all_scores": scores,
            }
            s = scores[best_n]
            logger.info(f"  [{domain}] 권장 n={best_n}σ "
                        f"(분리도={s['score']}, 정상={s['rel_results']}건, "
                        f"무관 차단={s['irr_block_rate']*100:.0f}%)")

    out_path = SCRIPTS_DIR / "n_sigma_analysis_v2.json"
    out_path.write_text(json.dumps(recommendations, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    logger.info(f"\n  저장: {out_path}")
    return recommendations


# ─── Step 3: Phase 1 쿼리 풀 확장 ────────────────────────────────────────────
EXPANDED_QUERIES = {
    "image": [
        "고양이", "강아지", "토끼", "기린", "호랑이", "사자", "원숭이", "코끼리",
        "햄버거", "피자", "초밥", "케이크", "샌드위치", "라면", "과일", "와인",
        "자동차", "비행기", "기차", "자전거", "선박", "로봇", "드론",
        "산", "바다", "강", "호수", "숲", "사막", "꽃", "노을", "구름", "별",
        "사람", "가족", "아기", "어린이", "운동", "공부", "요리", "여행",
        "도시 야경", "공원", "박물관", "공항", "지하철", "벚꽃", "단풍",
        "박스 안 고양이", "노을 지는 해변", "벚꽃 거리", "공원 어린이",
        "cat", "dog", "modern building", "vintage car", "ocean wave",
    ],
    "audio": [
        "고양이 모시고", "박춘봉 초밥", "AI 인공지능", "GPT OpenAI",
        "AI 검사 수사", "주식 투자", "코스피", "부동산",
        "음악", "다스뵈이다", "철학자", "윤석열", "검찰 개혁",
        "자율주행", "딥페이크", "유튜브", "한예종 강의",
        "정치 뉴스", "프로토타입", "AI가 AI를 개발",
        "바이브 코딩", "에너지 음료", "지식인 초대석",
        "통일교", "원영적 사고", "노이즈 캔슬링",
        "AI development", "podcast", "interview", "rock music",
        "vintage", "comedy show", "Korean drama",
    ],
    "doc": [
        "AI 인공지능", "주식 부동산", "환경 정책", "교육 개혁",
        "범죄 데이터", "농촌 토지", "자전거길", "공간 데이터",
        "보고서", "기술 발전", "디지털 정책",
        "건강 의료", "안전 규제", "에너지 관리",
        "도시 계획", "교통 인프라",
        "AI report", "policy document", "research paper",
    ],
    "bgm": [
        "잔잔한 음악", "신나는 비트", "슬픈 발라드", "긴장감 있는 음악",
        "재즈 피아노", "록 기타", "클래식 음악", "EDM 일렉트로닉",
        "기타 솔로", "피아노 연주", "드럼 비트",
        "빠른 템포", "느린 음악", "중간 템포",
        "soft jazz", "fast rock", "ambient electronic",
        "upbeat pop", "chill lofi", "dramatic orchestral",
        "acoustic guitar", "synthwave", "epic cinematic",
        "여름 해변 음악", "카페 음악", "운동 음악",
        "비 오는 날 카페", "잠들기 전 음악",
    ],
}


def fit_relevant_v2(domain: str, file_type: str, match_field: str,
                     rerank_min: float = -0.5, match_min: float = 0.30) -> dict | None:
    queries = EXPANDED_QUERIES.get(domain, [])
    cosines = []
    for i, q in enumerate(queries, 1):
        try:
            results = search(q, top_k=50, file_type=file_type)
        except Exception:
            continue
        for r in results:
            rs = r.get("rerank_score")
            mv = r.get(match_field) or r.get("dense")
            if rs is None or mv is None:
                continue
            if float(rs) >= rerank_min and float(mv) >= match_min:
                cosines.append(float(mv))
        if i % 10 == 0:
            logger.info(f"  [{domain}] {i}/{len(queries)} 진행, n={len(cosines)}")

    logger.info(f"  → [{domain}] relevant n={len(cosines)}")
    return _fit_beta(cosines) if len(cosines) >= 5 else None


def _fit_beta(samples):
    import numpy as np
    from scipy.stats import beta as beta_dist
    arr = np.asarray(samples, dtype=np.float64)
    s_min, s_max = float(arr.min()), float(arr.max())
    span = s_max - s_min
    if span < 1e-6:
        return None
    normalized = np.clip((arr - s_min) / span, 1e-4, 1 - 1e-4)
    try:
        a, b, _, _ = beta_dist.fit(normalized, floc=0, fscale=1)
        return {
            "n_samples": len(samples),
            "gaussian": {"mu": round(float(arr.mean()), 4),
                         "sigma": round(float(arr.std()), 4)},
            "beta": {"a": round(float(a), 4), "b": round(float(b), 4),
                     "loc": round(s_min, 4), "scale": round(span, 4)},
        }
    except Exception:
        return None


def step3_calibration_expand() -> dict:
    logger.info("═" * 60)
    logger.info("[3/4] Phase 1 calibration 쿼리 풀 확장 (n≥30 목표)")
    logger.info("═" * 60)

    if not wait_flask_ready(timeout=5):
        kill_flask(); start_flask_bg()
        if not wait_flask_ready():
            return {"error": "Flask not ready"}

    results = {}
    results["image"] = fit_relevant_v2("image", "image", "visual_match",
                                         rerank_min=-0.5, match_min=0.10)
    results["audio"] = fit_relevant_v2("audio", "audio", "audio_match",
                                         rerank_min=0.5, match_min=0.32)
    results["doc"]   = fit_relevant_v2("doc", "doc", "dense",
                                         rerank_min=-0.5, match_min=0.55)

    out_path = SCRIPTS_DIR / "calibration_v2.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    logger.info(f"\n  저장: {out_path}")
    return results


# ─── Step 4: BGM 카테고리 정성 분석 ──────────────────────────────────────────
BGM_CATEGORY_QUERIES = {
    "분위기-잔잔": ("잔잔한 음악", ["slow", "quiet", "soft"]),
    "분위기-신나는": ("신나는 비트", ["fast", "upbeat", "energetic"]),
    "분위기-슬픈": ("슬픈 발라드", ["slow", "sad", "melancholic", "ballad"]),
    "장르-재즈": ("재즈 피아노", ["jazz", "piano"]),
    "장르-록": ("fast rock", ["rock", "fast", "guitar"]),
    "악기-기타": ("기타 솔로", ["guitar", "solo"]),
    "악기-피아노": ("피아노 연주", ["piano"]),
    "템포-빠른": ("빠른 템포", ["fast"]),
    "영문-soft jazz": ("soft jazz", ["jazz", "soft", "slow"]),
    "영문-ambient": ("ambient electronic", ["ambient", "electronic"]),
}


def step4_bgm_qualitative() -> dict:
    logger.info("═" * 60)
    logger.info("[4/4] BGM 카테고리 정성 분석")
    logger.info("═" * 60)

    results = {}
    for cat, (query, expected_tags) in BGM_CATEGORY_QUERIES.items():
        try:
            res = search(query, top_k=3, file_type="bgm")
            cat_results = []
            for r in res:
                tags = r.get("tags", "") or ""
                if isinstance(tags, list):
                    tags = " ".join(tags)
                tags_lower = tags.lower()
                # 기대 태그 매칭 수 측정
                matched = sum(1 for t in expected_tags if t in tags_lower)
                cat_results.append({
                    "file": r.get("file_name"),
                    "tags": tags,
                    "expected": expected_tags,
                    "match_score": f"{matched}/{len(expected_tags)}",
                    "match_pct": round(matched / max(len(expected_tags), 1), 2),
                })
            avg_match = sum(c.get("match_pct", 0) for c in cat_results) / max(len(cat_results), 1)
            results[cat] = {
                "query": query,
                "n_results": len(res),
                "avg_match": round(avg_match, 2),
                "results": cat_results,
            }
            logger.info(f"  [{cat}] '{query}' n={len(res)} avg_match={avg_match:.2f}")
        except Exception as e:
            results[cat] = {"error": str(e)}

    out_path = SCRIPTS_DIR / "bgm_qualitative_v2.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    logger.info(f"\n  저장: {out_path}")
    return results


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    logger.info("═" * 60)
    logger.info("v2 후속 개선 통합 파이프라인 시작")
    logger.info("═" * 60)
    t0 = time.time()

    # Step 1
    s1 = step1_caption_lies_v2(threshold=0.20)
    # Step 2
    s2 = step2_n_sigma_v2()
    # Step 3 (Flask 필요)
    s3 = step3_calibration_expand()
    # Step 4 (Flask 필요)
    s4 = step4_bgm_qualitative()

    # 통합 마크다운
    md = ["# v2 후속 개선 통합 결과\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
          f"소요: {(time.time()-t0)/60:.1f}분\n\n"]

    md.append("## 1. 캡션 거짓말 재검사 (threshold=0.20)\n")
    if "error" in s1:
        md.append(f"⚠️ {s1['error']}\n\n")
    else:
        md.append(f"- 캡션 있는 이미지 중 의심 캡션: **{s1.get('n_suspects', 0)}건** "
                  f"({s1.get('n_total', 0)}개 중)\n")
        md.append("- 자세한 내용: `scripts/real_caption_lies_v2.json`\n\n")

    md.append("## 2. n_sigma 권장 (분리도 기반)\n")
    md.append("| 도메인 | 권장 n | 분리도 | 정상 결과 | 무관 차단율 |\n")
    md.append("|--------|--------|-------|----------|-----------|\n")
    if "error" not in s2:
        for dom, rec in s2.items():
            best = rec.get("all_scores", {}).get(rec.get("recommended_n"), {})
            md.append(f"| {dom} | {rec.get('recommended_n')}σ | "
                      f"{rec.get('best_score')} | "
                      f"{best.get('rel_results', '?')} | "
                      f"{int(best.get('irr_block_rate', 0)*100)}% |\n")
    md.append("\n")

    md.append("## 3. Calibration 확장 (60+ 쿼리)\n")
    md.append("| 도메인 | n | μ | σ |\n")
    md.append("|--------|---|---|---|\n")
    for dom in ["image", "audio", "doc"]:
        r = s3.get(dom)
        if r:
            g = r.get("gaussian", {})
            md.append(f"| {dom} | {r.get('n_samples')} | "
                      f"{g.get('mu')} | {g.get('sigma')} |\n")
    md.append("\n")

    md.append("## 4. BGM 카테고리 정성 분석\n")
    md.append("| 카테고리 | 쿼리 | n | avg_match |\n")
    md.append("|---------|------|---|-----------|\n")
    for cat, r in s4.items():
        if "error" not in r:
            md.append(f"| {cat} | {r.get('query')} | "
                      f"{r.get('n_results')} | {r.get('avg_match')} |\n")
    md.append("\n")

    out_path = SCRIPTS_DIR / "v2_summary.md"
    out_path.write_text("".join(md), encoding="utf-8")

    logger.info("═" * 60)
    logger.info(f"전체 완료 — 소요 {(time.time()-t0)/60:.1f}분")
    logger.info("산출물:")
    logger.info("  scripts/real_caption_lies_v2.json")
    logger.info("  scripts/n_sigma_analysis_v2.json")
    logger.info("  scripts/calibration_v2.json")
    logger.info("  scripts/bgm_qualitative_v2.json")
    logger.info("  scripts/v2_summary.md (통합 요약)")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
