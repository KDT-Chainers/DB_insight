"""
hwpx_extractor.py
──────────────────────────────────────────────────────────────────────────────
HWPX(한글 문서) 텍스트 추출.

HWPX 는 ZIP 구조 안에 XML 파일이 담긴 포맷.
  Contents/section0.xml, section1.xml ... → 본문 텍스트
  Contents/header.xml                     → 스타일 정보 (스킵)

파싱 대상:
  - <hp:t> : 일반 텍스트
  - <hp:cellTr>, <hp:cellTd> : 표 셀 텍스트
  - <hp:para> : 문단 구분자 (줄바꿈)
"""
from __future__ import annotations

import logging
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple

from lxml import etree

logger = logging.getLogger(__name__)

# HWPX XML 네임스페이스
_NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hh": "http://www.hancom.co.kr/hwpml/2011/hwpunit",
}


def extract_hwpx(path: str | Path) -> List[Tuple[int, str]]:
    """
    HWPX 파일에서 섹션별 텍스트 추출.

    Args:
        path: .hwpx 파일 경로

    Returns:
        List of (section_number, text) — 1-indexed
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"HWPX 파일 없음: {path}")

    sections: List[Tuple[int, str]] = []

    try:
        with zipfile.ZipFile(path, "r") as zf:
            # Contents/section0.xml, section1.xml, ... 탐색
            section_files = sorted([
                name for name in zf.namelist()
                if name.startswith("Contents/section") and name.endswith(".xml")
            ])

            if not section_files:
                # 구버전 HWP XML 구조 시도
                section_files = sorted([
                    name for name in zf.namelist()
                    if "section" in name.lower() and name.endswith(".xml")
                ])

            if not section_files:
                logger.warning("섹션 XML 없음: %s", path.name)
                return []

            for idx, section_file in enumerate(section_files, start=1):
                xml_bytes = zf.read(section_file)
                text = _parse_section_xml(xml_bytes)
                sections.append((idx, text))

    except zipfile.BadZipFile:
        logger.error("유효하지 않은 HWPX 파일(ZIP 오류): %s", path.name)
    except Exception as exc:
        logger.error("HWPX 파싱 오류: %s — %s", path.name, exc)

    return sections


def extract_hwpx_with_metadata(path: str | Path) -> List[Dict[str, Any]]:
    """
    HWPX 파일에서 섹션 텍스트와 메타데이터를 함께 추출한다.
    원본 파일은 절대 수정하지 않는다.

    반환 형식:
        [
            {
                "text":        str,
                "page_number": int,   # HWPX 섹션 번호 기반 (1-indexed)
                "bbox":        None,  # HWPX는 bbox 추출 불가
                "source_path": str
            },
            ...
        ]
    """
    path = Path(path).resolve()
    source_path = str(path)
    sections = extract_hwpx(path)
    return [
        {"text": t, "page_number": n, "bbox": None, "source_path": source_path}
        for n, t in sections
    ]


def _parse_section_xml(xml_bytes: bytes) -> str:
    """
    섹션 XML 에서 텍스트 노드를 순서대로 수집.

    <hp:para> 를 만날 때마다 줄바꿈을 삽입해 문단 구조를 유지.
    표 셀(<hp:cellTd>) 텍스트는 탭으로 구분 후 줄바꿈으로 닫음.
    """
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        logger.warning("XML 파싱 오류: %s", exc)
        return ""

    lines: List[str] = []
    _collect_text(root, lines)
    return "\n".join(lines)


def _collect_text(node: etree._Element, lines: List[str]) -> None:
    """
    XML 트리를 재귀 탐색하며 텍스트 수집.
    문단/셀 구조에 맞게 줄바꿈·탭 삽입.
    """
    tag = etree.QName(node.tag).localname if node.tag else ""

    if tag == "para":
        # 문단 시작: 현재까지 모은 텍스트를 한 줄로 구분
        para_texts: List[str] = []
        for child in node:
            _collect_inline(child, para_texts)
        line = "".join(para_texts).strip()
        if line:
            lines.append(line)
        return  # 자식은 이미 처리

    if tag in ("cellTr",):
        # 표 행: 셀들을 탭으로 연결
        cell_texts: List[str] = []
        for child in node:
            if etree.QName(child.tag).localname in ("cellTd", "cell"):
                cell_line: List[str] = []
                for sub in child.iter():
                    if etree.QName(sub.tag).localname == "t" and sub.text:
                        cell_line.append(sub.text)
                cell_texts.append("".join(cell_line))
        lines.append("\t".join(cell_texts))
        return

    # 기타 노드: 자식 재귀
    for child in node:
        _collect_text(child, lines)


def _collect_inline(node: etree._Element, buf: List[str]) -> None:
    """인라인 텍스트(<hp:t>) 수집"""
    tag = etree.QName(node.tag).localname if node.tag else ""
    if tag == "t" and node.text:
        buf.append(node.text)
    for child in node:
        _collect_inline(child, buf)
