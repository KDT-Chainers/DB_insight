"""routes/security_mask.py — 이미지 PII 탐지 & 모자이크 마스킹 API.

security/ 모듈의 로직을 재사용:
  - EasyOCR → 텍스트 + bbox 추출
  - 정규식 기반 PII 탐지 (주민번호·여권·계좌번호·전화번호 등 한국형 6종 포함)
  - PIL 픽셀화 모자이크 → base64 PNG 반환

GET  /api/security/mask_image?path=<relative_img_path>&domain=<image|doc_page>
  → { masked_b64: str, pii_found: bool, pii_types: list, regions_count: int }
"""
from __future__ import annotations

import base64
import io
import logging
import re
import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from config import PATHS

logger = logging.getLogger(__name__)

security_mask_bp = Blueprint("security_mask", __name__, url_prefix="/api/security")

# ── PII 정규식 패턴 ────────────────────────────────────────────────────────────
# OCR 출력 변형 대응:
#   KR_RRN: "820701-2345678" / "820701 - 2345678" / "820701 — 2345678" 모두 매칭
_PII_PATTERNS: list[tuple[str, str]] = [
    ("KR_RRN",            r"\b\d{6}\s*[-–—]\s*\d{7}\b"),        # 주민등록번호 (공백±하이픈)
    ("KR_RRN_SPACE",      r"\b\d{6}\s+\d{7}\b"),                 # 주민번호 공백 구분
    ("KR_PASSPORT",       r"\b[A-Za-z]\d{8}\b"),          # 여권번호 (OCR 소문자 대응)
    ("KR_DRIVER_LICENSE", r"\b\d{2}-\d{2}-\d{6}-\d{2}\b"),
    ("KR_BANK_ACCOUNT",   r"\b\d{3,4}[-\s]\d{2,4}[-\s]\d{4,6}\b"),
    ("KR_BRN",            r"\b\d{3}-\d{2}-\d{5}\b"),
    ("KR_PHONE",          r"\b(?:010|011|016|017|018|019|02|\d{3})[\s-]\d{3,4}[\s-]\d{4}\b"),
    ("EMAIL",             r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
    ("CREDIT_CARD",       r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b"),
]


def _detect_pii_in_blocks(ocr_blocks: list[tuple]) -> list[dict[str, Any]]:
    """OCR 블록별로 PII 탐지 → 해당 bbox 목록 반환.

    인접 블록을 라인별로 합쳐 다중 토큰 패턴(예: '820701 - 2345678')도 탐지한다.
    """
    pii_bboxes: list[dict[str, Any]] = []
    seen_regions: set[tuple] = set()

    def _add_region(bbox_pts: list, found_types: list, text: str) -> None:
        xs = [p[0] for p in bbox_pts]
        ys = [p[1] for p in bbox_pts]
        key = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
        if key in seen_regions:
            return
        seen_regions.add(key)
        pii_bboxes.append({
            "x": key[0], "y": key[1],
            "w": key[2] - key[0],
            "h": key[3] - key[1],
            "types": found_types,
            "text_preview": text[:20] + ("…" if len(text) > 20 else ""),
        })

    # 1) 블록 단독 매칭
    for bbox, text, _conf in ocr_blocks:
        found_types = [lbl for lbl, pat in _PII_PATTERNS if re.search(pat, text)]
        if found_types:
            _add_region(bbox, found_types, text)

    # 2) 인접 블록 쌍(슬라이딩 윈도우) 합체 매칭 — "820701" + "- 2345678" 분리 케이스 대응
    for i in range(len(ocr_blocks) - 1):
        b1, t1, _ = ocr_blocks[i]
        b2, t2, _ = ocr_blocks[i + 1]
        merged_text = t1 + " " + t2
        found_types = [lbl for lbl, pat in _PII_PATTERNS if re.search(pat, merged_text)]
        if found_types:
            all_pts = b1 + b2
            _add_region(all_pts, found_types, merged_text)

    return pii_bboxes


def _mosaic_regions(img, regions: list[dict]) -> "PIL.Image.Image":
    """PIL 이미지에 모자이크(1/10 픽셀화) 적용 — 원본 불변, 사본 반환."""
    result = img.copy()
    for r in regions:
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        if w <= 0 or h <= 0:
            continue
        x2 = min(x + w, result.width)
        y2 = min(y + h, result.height)
        crop = result.crop((x, y, x2, y2))
        small = crop.resize(
            (max(1, crop.width // 10), max(1, crop.height // 10)),
            resample=0,   # NEAREST
        )
        mosaic = small.resize((crop.width, crop.height), resample=0)
        result.paste(mosaic, (x, y))
    return result


def _img_to_b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@security_mask_bp.get("/mask_image")
def mask_image():
    """이미지 경로를 받아 PII 탐지 후 모자이크 처리된 base64 이미지 반환."""
    rel  = request.args.get("path", "").strip()
    domain = request.args.get("domain", "image")

    if not rel:
        return jsonify({"error": "path 필수"}), 400
    if ".." in rel:
        return jsonify({"error": "허용되지 않은 경로"}), 400

    # 경로 해석
    if domain == "image":
        img_path = Path(PATHS["RAW_DB"]) / "Img" / rel
    else:
        img_path = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / rel

    if not img_path.exists():
        return jsonify({"error": "파일 없음"}), 404

    # PIL 로드
    try:
        from PIL import Image
        img = Image.open(img_path).convert("RGB")
    except Exception as e:
        return jsonify({"error": f"이미지 로드 실패: {e}"}), 500

    # EasyOCR 시도
    try:
        import easyocr
        import numpy as np

        # 전처리: 업스케일 + 대비 강화 + 그레이스케일 (security 모듈 동일)
        from PIL import ImageEnhance
        proc = img.copy()
        w, h = proc.size
        if max(w, h) < 1200:
            scale = 1200 / max(w, h)
            proc = proc.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        proc = ImageEnhance.Contrast(proc).enhance(2.5)
        proc = proc.convert("L").convert("RGB")

        reader = easyocr.Reader(["en", "ko"], gpu=False, verbose=False)
        ocr_results = reader.readtext(np.array(proc), detail=1, paragraph=False)

        # 스케일 역변환 (bbox 좌표를 원본 이미지 기준으로)
        scale_x = img.width / proc.width
        scale_y = img.height / proc.height
        scaled_ocr = []
        for bbox, text, conf in ocr_results:
            scaled_bbox = [[int(p[0] * scale_x), int(p[1] * scale_y)] for p in bbox]
            scaled_ocr.append((scaled_bbox, text, conf))

        pii_regions = _detect_pii_in_blocks(scaled_ocr)

    except ImportError:
        # EasyOCR 없으면 전체 이미지 마스킹 (보수적 접근)
        logger.warning("[security_mask] EasyOCR 미설치 — 전체 이미지 마스킹")
        pii_regions = [{
            "x": 0, "y": 0,
            "w": img.width, "h": img.height,
            "types": ["UNKNOWN"], "text_preview": "",
        }]
    except Exception as e:
        logger.exception("[security_mask] OCR 실패")
        return jsonify({"error": f"OCR 실패: {e}"}), 500

    pii_found  = len(pii_regions) > 0
    pii_types  = list({t for r in pii_regions for t in r.get("types", [])})

    if pii_found:
        masked = _mosaic_regions(img, pii_regions)
        masked_b64 = _img_to_b64(masked)
    else:
        masked_b64 = _img_to_b64(img)   # PII 없으면 원본 그대로

    return jsonify({
        "pii_found":     pii_found,
        "pii_types":     pii_types,
        "regions_count": len(pii_regions),
        "masked_b64":    masked_b64,
    })
