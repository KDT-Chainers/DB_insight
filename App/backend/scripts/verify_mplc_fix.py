"""verify_mplc_fix.py — v14 MPLC 수정 검증 (서버 불필요)

Image MPLC 수정 후 점수 분포 변화를 수치로 확인.
"""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services.mplc_scoring import compute_mplc_score, _sigmoid
from services.score_adjust import _generous_curve

print("=" * 60)
print("v14 MPLC 수정 검증")
print("=" * 60)

# ── Image MPLC 검증 ──────────────────────────────────────────
print("\n[Image MPLC]")
print("  raw_dense  | gc(dense) | MPLC_v14 | MPLC_old (bug)")
print("  -----------+-----------+----------+---------------")
for raw in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
    gc = _generous_curve(raw)
    mplc_v14 = _sigmoid((gc - 0.6) * 10.0)            # 수정 버전
    mplc_old  = _sigmoid((raw - 0.6) * 10.0)           # 구 버전 (bug)
    print(f"  {raw:.2f}       | {gc:.3f}     | {mplc_v14:.3f}    | {mplc_old:.3f}")

# ── 실제 결과 dict로 compute_mplc_score 호출 ──────────────────
print("\n[compute_mplc_score 직접 호출]")

# 좋은 이미지 매칭 시뮬레이션
good_img = {"dense": 0.42, "z_score": 0.97, "lexical": 0, "asf": 0,
            "rerank_score": 0, "file_name": "cat_photo.jpg",
            "file_path": "raw/Img/cat_photo.jpg", "snippet": ""}
score_img = compute_mplc_score(good_img, "image", "고양이 사진")
print(f"  좋은 이미지 (raw_dense=0.42, z=0.97): MPLC={score_img:.3f}  (목표: >0.80)")

# 노이즈 이미지 (doc 쿼리에서)
noise_img = {"dense": 0.25, "z_score": 0.60, "lexical": 0, "asf": 0,
             "rerank_score": 0, "file_name": "random_chart.jpg",
             "file_path": "raw/Img/random_chart.jpg", "snippet": ""}
score_noise = compute_mplc_score(noise_img, "image", "재정건전화법안 입법과제")
print(f"  노이즈 이미지 (raw_dense=0.25, z=0.60): MPLC={score_noise:.3f}  (목표: <0.30)")

# 좋은 doc 매칭
good_doc = {"dense": 0.60, "z_score": 0.92, "lexical": 0.4, "asf": 0.3,
            "rerank_score": 0, "file_name": "AI정책보고서.pdf",
            "file_path": "raw/Doc/AI정책보고서.pdf", "snippet": "AI 정책"}
score_doc = compute_mplc_score(good_doc, "doc", "AI 기술 동향")
print(f"  좋은 doc (raw_dense=0.60, z=0.92): MPLC={score_doc:.3f}  (목표: 0.40~0.70)")

# Audio 파일명 boost 테스트
audio_filename = {"dense": 0.85, "z_score": 1.2, "lexical": 0, "asf": 0,
                  "rerank_score": 0, "file_name": "다스뵈이다_E001.mp3",
                  "file_path": "/raw/Rec/다스뵈이다_E001.mp3", "snippet": "",
                  "confidence": 0.60}  # filename boost로 이미 0.60
score_audio = compute_mplc_score(audio_filename, "audio", "다스뵈이다")
print(f"  오디오 파일명 boost (z_raw=1.2, conf=0.60): MPLC={score_audio:.3f}")

# apply_mplc_to_results의 max(score, prev*0.95) 보존 확인
from services.mplc_scoring import apply_mplc_to_results
results_test = {
    "audio": [dict(audio_filename)],
}
apply_mplc_to_results(results_test, "다스뵈이다")
final_conf = results_test["audio"][0]["confidence"]
print(f"  apply_mplc 후 confidence (max 보존): {final_conf:.3f}  (목표: ≥0.57)")

# ── 교차 도메인 비교 ──────────────────────────────────────────
print("\n[교차 도메인 MPLC 비교 — 이미지 쿼리]")
print("  도메인  | MPLC  | 기대 winner")
r_cat_img = {"dense": 0.42, "z_score": 0.97, "lexical": 0, "asf": 0,
             "rerank_score": 0, "file_name": "cat.jpg", "file_path": "/Img/cat.jpg", "snippet": ""}
r_cat_doc = {"dense": 0.38, "z_score": 0.85, "lexical": 0.1, "asf": 0.05,
             "rerank_score": 0, "file_name": "동물학.pdf", "file_path": "/Doc/동물학.pdf", "snippet": "고양이"}
s_img = compute_mplc_score(r_cat_img, "image", "고양이 사진")
s_doc = compute_mplc_score(r_cat_doc, "doc", "고양이 사진")
print(f"  image   | {s_img:.3f} | ← 이겨야 함")
print(f"  doc     | {s_doc:.3f} | ← 져야 함")
winner = "image ✓" if s_img > s_doc else "doc ✗ (버그 남음)"
print(f"  결과: {winner}")

print("\n[교차 도메인 MPLC 비교 — doc 쿼리]")
r_ai_doc = {"dense": 0.65, "z_score": 0.95, "lexical": 0.5, "asf": 0.4,
            "rerank_score": 0, "file_name": "AI정책.pdf", "file_path": "/Doc/AI정책.pdf", "snippet": "AI 정책"}
r_ai_img = {"dense": 0.32, "z_score": 0.80, "lexical": 0, "asf": 0,
            "rerank_score": 0, "file_name": "infographic.jpg", "file_path": "/Img/infographic.jpg", "snippet": ""}
s_doc2 = compute_mplc_score(r_ai_doc, "doc", "AI 정책 동향")
s_img2 = compute_mplc_score(r_ai_img, "image", "AI 정책 동향")
print(f"  doc     | {s_doc2:.3f} | ← 이겨야 함")
print(f"  image   | {s_img2:.3f} | ← 져야 함")
winner2 = "doc ✓" if s_doc2 > s_img2 else "image ✗ (회귀 발생)"
print(f"  결과: {winner2}")

print("\n" + "=" * 60)
print("검증 완료. 서버 시작 후 start_fix_evaluate.bat 실행하세요.")
print("=" * 60)
