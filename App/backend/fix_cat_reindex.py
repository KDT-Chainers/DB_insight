"""fix_cat_reindex.py — real_cat_31/32/33 캡션 수정 후 GPU 재임베딩.

실행 방법 (backend 디렉토리에서):
    python fix_cat_reindex.py

작업 순서:
  1) registry.json 에서 3개 항목 SHA 초기화 (재처리 강제)
  2) captions_triple.jsonl L1/L2/L3 업데이트
  3) run_image_incremental() 실행 → GPU 3축 재임베딩 + lexical rebuild + calibration
"""
import json
import sys
import io
from pathlib import Path

# Windows cp949 콘솔 인코딩 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 경로 설정 ────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import PATHS

REGISTRY_PATH  = Path(PATHS["TRICHEF_IMG_CACHE"]) / "registry.json"
CAPTIONS_JSONL = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / ".." / ".." / \
                 "embedded_DB" / "Img" / "captions_triple.jsonl"
# 실제 경로 정규화
CAPTIONS_JSONL = CAPTIONS_JSONL.resolve()

TARGET_KEYS = [
    "영진_7차/real_cat_31.jpg",
    "영진_7차/real_cat_32.jpg",
    "영진_7차/real_cat_33.jpg",
]

NEW_CAPTIONS = {
    "영진_7차/real_cat_31.jpg": {
        "L1": "고양이가 실내에서 편안히 쉬고 있는 모습이다.",
        "L2": "고양이, cat, kitten, feline, domestic cat, pet, 집고양이, resting, indoors",
        "L3": "고양이가 실내에서 편안히 쉬고 있는 모습이다. 부드럽고 포근한 털을 가진 고양이가 눈을 반쯤 감고 여유롭게 앉아 있다. 귀여운 집고양이의 일상적인 모습. cat resting indoors, cute domestic cat, feline, kitten, pet cat, 고양이, 집고양이",
    },
    "영진_7차/real_cat_32.jpg": {
        "L1": "고양이가 카메라를 바라보며 앉아 있는 모습이다.",
        "L2": "고양이, cat, kitten, feline, domestic cat, pet, 반려묘, sitting, camera",
        "L3": "고양이가 카메라를 바라보며 앉아 있는 모습이다. 호기심 어린 눈으로 정면을 응시하는 귀여운 고양이의 얼굴이 클로즈업 되어 있다. 사랑스러운 반려묘. cat sitting looking at camera, cute cat face, adorable feline, domestic cat, pet, 고양이, 반려묘, 집고양이",
    },
    "영진_7차/real_cat_33.jpg": {
        "L1": "고양이가 바닥에 편안하게 누워 쉬고 있는 모습이다.",
        "L2": "고양이, cat, kitten, feline, domestic cat, pet, 집고양이, lying, sleeping, relaxing",
        "L3": "고양이가 바닥에 편안하게 누워 쉬고 있는 모습이다. 몸을 동그랗게 말고 낮잠을 자거나 여유롭게 스트레칭하는 고양이. 따뜻한 실내에서 휴식을 취하는 귀여운 집고양이. cat lying down relaxing, sleeping cat, lazy cat, domestic cat resting, cute kitten, feline, 고양이, 낮잠, 집고양이",
    },
}


def step1_clear_registry():
    """registry.json 에서 3개 항목 SHA 초기화."""
    print("[1/3] registry.json SHA 초기화...")
    if not REGISTRY_PATH.exists():
        print(f"  ⚠ registry 없음: {REGISTRY_PATH}")
        return
    reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = 0
    for key in TARGET_KEYS:
        if key in reg:
            reg[key]["sha"] = ""   # SHA 비워두면 incremental runner 가 재처리
            print(f"  ✓ SHA 초기화: {key}")
            changed += 1
        else:
            print(f"  ⚠ registry 항목 없음: {key}")
    if changed:
        REGISTRY_PATH.write_text(
            json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"  → {changed}개 초기화 완료")


def step2_update_captions_jsonl():
    """captions_triple.jsonl L1/L2/L3 업데이트."""
    print("[2/3] captions_triple.jsonl 업데이트...")
    if not CAPTIONS_JSONL.exists():
        print(f"  ⚠ captions_triple.jsonl 없음: {CAPTIONS_JSONL}")
        return

    lines = CAPTIONS_JSONL.read_text(encoding="utf-8").splitlines()
    updated = 0
    new_lines = []
    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue
        try:
            obj = json.loads(line)
            rel = obj.get("rel", "")
            # rel 형식이 "영진_7차/real_cat_31.jpg" 이거나 경로 슬래시 혼용 대응
            norm = rel.replace("\\", "/")
            matched_key = None
            for k in TARGET_KEYS:
                if norm.endswith(k) or norm == k:
                    matched_key = k
                    break
            if matched_key:
                obj["L1"] = NEW_CAPTIONS[matched_key]["L1"]
                obj["L2"] = NEW_CAPTIONS[matched_key]["L2"]
                obj["L3"] = NEW_CAPTIONS[matched_key]["L3"]
                new_lines.append(json.dumps(obj, ensure_ascii=False))
                updated += 1
                print(f"  ✓ 업데이트: {rel}")
            else:
                new_lines.append(line)
        except json.JSONDecodeError:
            new_lines.append(line)

    CAPTIONS_JSONL.write_text("\n".join(new_lines), encoding="utf-8")
    print(f"  → {updated}개 라인 업데이트 완료")


def step3_run_incremental():
    """GPU 3축 재임베딩 실행."""
    print("[3/3] GPU 재임베딩 시작...")
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  장치: {device}")
    if device == "cpu":
        print("  ⚠ GPU 없음 — CPU로 실행 (느릴 수 있음)")

    from embedders.trichef.incremental_runner import run_image_incremental
    result = run_image_incremental()
    print(f"  → 완료: 신규={result.new}, 기존={result.existing}, 전체={result.total}")
    return result


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("=" * 60)
    print("real_cat_31/32/33 재임베딩 시작")
    print("=" * 60)

    step1_clear_registry()
    step2_update_captions_jsonl()
    result = step3_run_incremental()

    print("=" * 60)
    if result.new >= 3:
        print(f"✅ 성공: {result.new}개 이미지 재임베딩 완료")
    else:
        print(f"⚠ 예상보다 적은 재처리: {result.new}개 (3개 기대)")
        print("   registry.json 을 확인하거나 직접 SHA 를 삭제하고 재실행하세요.")
    print("=" * 60)
