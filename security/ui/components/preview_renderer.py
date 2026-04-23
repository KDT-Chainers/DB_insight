"""
ui/components/preview_renderer.py
──────────────────────────────────────────────────────────────────────────────
마스킹 텍스트 렌더러 + 이미지 모자이크 렌더러.

ABC Rule: [C] 렌더링 출력 생성만 담당.
          원본 파일을 절대 수정하지 않으며, 처리된 이미지는 메모리에서만 사용한다.
          디스크에 저장하지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ── PII 유형별 마스킹 패턴 ──────────────────────────────────────────────────────

# 각 PII 유형에 대해 (정규식 패턴, 마스킹 함수) 튜플
_MASKING_RULES: List[tuple] = [
    # 주민등록번호: 123456-1234567 → ******-*******
    (r"\b(\d{6})-(\d{7})\b",                    lambda m: "●●●●●●-●●●●●●●"),
    # 여권번호: M12345678 → M*******8
    (r"\b([A-Z])(\d{6,8})(\d)\b",               lambda m: m.group(1) + "●" * len(m.group(2)) + m.group(3)),
    # 운전면허: 12-34-567890-12 형태
    (r"\b(\d{2})-(\d{2})-(\d{6})-(\d{2})\b",    lambda m: "●●-●●-●●●●●●-●●"),
    # 계좌번호: 숫자 3-4묶음 (하이픈 또는 공백)
    (r"\b(\d{3,4})[-\s](\d{2,4})[-\s](\d{4,6})\b",
                                                  lambda m: "●●●●-●●-●●●" + m.group(3)[-4:]),
    # 사업자등록번호: 123-45-67890
    (r"\b(\d{3})-(\d{2})-(\d{5})\b",            lambda m: "●●●-●●-●●●●●"),
    # 전화번호: 010-1234-5678
    (r"\b(01[0-9])-(\d{3,4})-(\d{4})\b",        lambda m: m.group(1) + "-●●●●-" + m.group(3)[-2:] + "●●"),
    # 이메일
    (r"\b([a-zA-Z0-9._%+\-]{1,3})[a-zA-Z0-9._%+\-]*@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b",
                                                  lambda m: m.group(1) + "●●●@" + m.group(2)),
]

# PresidioAnalyzerResult 또는 dict 형태의 finding을 처리하기 위한 어댑터
def _get_finding_span(finding: Any) -> Optional[tuple]:
    """finding에서 (start, end, entity_type)을 추출한다."""
    if isinstance(finding, dict):
        return finding.get("start"), finding.get("end"), finding.get("entity_type", "")
    start  = getattr(finding, "start", None)
    end    = getattr(finding, "end", None)
    entity = getattr(finding, "entity_type", "")
    return start, end, entity


def render_masked_text(text: str, pii_results: Optional[List[Any]] = None) -> str:
    """
    PII 위치 또는 정규식 패턴을 기반으로 텍스트를 마스킹하여 반환한다.
    원본 텍스트는 절대 수정하지 않는다. 렌더링용 사본만 처리한다.

    마스킹 우선순위:
      1. pii_results(AnalyzerResult) — 정확한 위치 기반 마스킹
      2. 내장 정규식 규칙 — 위치 정보 없을 때 패턴 기반 마스킹

    Args:
        text:        마스킹할 텍스트 (원본 보존 — 이 함수 내에서만 사본 사용)
        pii_results: Presidio AnalyzerResult 리스트 또는 dict 리스트 (선택)

    Returns:
        마스킹된 렌더링용 텍스트
    """
    if not text:
        return text

    # 렌더링용 사본 생성 (원본 불변)
    masked = text

    # 1차: Presidio findings 기반 마스킹 (위치 정보 활용)
    if pii_results:
        # 위치 기준 역순 처리 (앞 부분 교체 시 뒤 인덱스 변동 방지)
        valid_spans = []
        for finding in pii_results:
            start, end, entity = _get_finding_span(finding)
            if start is not None and end is not None and end > start:
                valid_spans.append((int(start), int(end), str(entity)))

        valid_spans.sort(key=lambda x: x[0], reverse=True)

        for start, end, entity in valid_spans:
            if end > len(masked):
                continue
            original_span = masked[start:end]
            masked_span   = _mask_span(original_span, entity)
            masked = masked[:start] + masked_span + masked[end:]

    # 2차: 정규식 기반 추가 마스킹 (findings에서 놓친 패턴 보완)
    for pattern, mask_fn in _MASKING_RULES:
        masked = re.sub(pattern, mask_fn, masked)

    return masked


def _mask_span(text: str, entity_type: str) -> str:
    """
    엔티티 유형에 맞는 마스킹 형태를 반환한다.

    Args:
        text:        마스킹할 원본 스팬 텍스트
        entity_type: Presidio 엔티티 유형

    Returns:
        마스킹된 텍스트 (동일한 길이로 유지)
    """
    entity_upper = entity_type.upper()

    if entity_upper == "KR_RRN":
        return "●●●●●●-●●●●●●●"
    if entity_upper == "KR_PASSPORT":
        if len(text) >= 2:
            return text[0] + "●" * (len(text) - 2) + text[-1]
        return "●" * len(text)
    if entity_upper == "KR_DRIVER_LICENSE":
        return "●●-●●-●●●●●●-●●"
    if entity_upper == "KR_BANK_ACCOUNT":
        if len(text) > 4:
            return "●●●●" + text[-4:]
        return "●" * len(text)
    if entity_upper == "KR_BRN":
        return "●●●-●●-●●●●●"
    if entity_upper == "PERSON":
        if len(text) >= 3:
            return text[0] + "●" * (len(text) - 2) + text[-1]
        return text[0] + "●" * (len(text) - 1)
    if entity_upper in ("EMAIL_ADDRESS", "EMAIL"):
        at_idx = text.find("@")
        if at_idx > 1:
            return text[:2] + "●●●" + text[at_idx:]
        return "●●●@●●●"
    if entity_upper in ("PHONE_NUMBER", "PHONE"):
        return "●●●-●●●●-●●●●"

    # 기본: 길이 유지하며 전체 마스킹
    return "●" * len(text)


def render_mosaic_image(
    image_path: str,
    pii_regions: Optional[List[Dict[str, Any]]] = None,
) -> "PIL.Image.Image":
    """
    이미지 내 PII 영역에 모자이크(픽셀화) 처리를 적용하여 메모리 내 PIL 이미지를 반환한다.

    원본 이미지 파일은 절대 수정하지 않는다.
    처리된 이미지는 메모리에서만 사용하며 디스크에 저장하지 않는다.

    모자이크 처리 방식:
      - PIL로 해당 영역만 크롭
      - 1/10 크기로 축소 후 원래 크기로 확대 (픽셀화 효과)
      - 원본 이미지 위에 오버레이

    Args:
        image_path:  원본 이미지 파일 경로 (읽기 전용)
        pii_regions: PII 위치 영역 리스트. 각 항목: {"x": int, "y": int, "w": int, "h": int}
                     None 또는 빈 리스트면 전체 이미지에 모자이크 적용

    Returns:
        모자이크 처리된 PIL Image 객체 (메모리 전용)
    """
    try:
        from PIL import Image
    except ImportError:
        raise ImportError("Pillow가 설치되어 있지 않습니다: pip install Pillow")

    # 원본 이미지 로드 (읽기 전용 — 파일 미수정)
    img = Image.open(image_path).convert("RGB")
    result = img.copy()  # 사본에만 작업

    regions = pii_regions or []

    if not regions:
        # 전체 이미지 모자이크
        w, h = result.size
        regions = [{"x": 0, "y": 0, "w": w, "h": h}]

    for region in regions:
        x = int(region.get("x", 0))
        y = int(region.get("y", 0))
        w = int(region.get("w", 0))
        h = int(region.get("h", 0))

        if w <= 0 or h <= 0:
            continue

        x2 = min(x + w, result.width)
        y2 = min(y + h, result.height)

        # 해당 영역 크롭
        crop = result.crop((x, y, x2, y2))

        # 1/10로 축소 후 원래 크기로 확대 → 픽셀화
        mosaic_size = max(1, crop.width // 10), max(1, crop.height // 10)
        small = crop.resize(mosaic_size, Image.NEAREST)
        mosaic = small.resize((crop.width, crop.height), Image.NEAREST)

        # 원본 사본에 오버레이
        result.paste(mosaic, (x, y))

    return result  # 메모리 전용, 디스크 저장 금지
