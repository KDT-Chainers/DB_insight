"""SSOT for App/backend 도메인의 지원 파일 확장자.

도메인 격리 원칙: DI/MR 모듈은 이 파일을 import 하지 않음.
DI_TriCHEF/_extensions.py 와 MR_TriCHEF/pipeline/_extensions.py 가
같은 정의를 독립 보유하고, tests/test_extensions_parity.py 가 동기화 검증.
"""
from __future__ import annotations

# Image (PIL native + pillow_heif/pillow_avif plugin)
IMG_EXTS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff",
    ".heic", ".heif", ".avif",
})

# Video (ffmpeg)
VID_EXTS: frozenset[str] = frozenset({
    ".mp4", ".avi", ".mov", ".mkv", ".wmv",
    ".webm", ".flv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts",
})

# Audio (ffmpeg + soundfile)
AUD_EXTS: frozenset[str] = frozenset({
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma",
    ".opus", ".aiff", ".aif", ".amr",
})

# Doc (분기 처리)
DOC_PDF_EXTS:    frozenset[str] = frozenset({".pdf"})
DOC_OFFICE_EXTS: frozenset[str] = frozenset({
    ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
    ".odt", ".odp", ".ods", ".rtf",
})
DOC_HWP_EXTS:    frozenset[str] = frozenset({".hwp", ".hwpx"})
DOC_TEXT_EXTS:   frozenset[str] = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".log",
    ".csv", ".tsv", ".html", ".htm",
})
DOC_EBOOK_EXTS:  frozenset[str] = frozenset({".epub"})

DOC_EXTS: frozenset[str] = (
    DOC_PDF_EXTS | DOC_OFFICE_EXTS | DOC_HWP_EXTS | DOC_TEXT_EXTS | DOC_EBOOK_EXTS
    | IMG_EXTS   # raw_DB/Doc/ 안의 이미지(주민등록증.webp 등)도 doc_page 도메인으로 색인
)

# 단일 도메인 진입점들이 사용 (image/doc 페이지 파일)
IMAGE_EMBED_EXTS: frozenset[str] = IMG_EXTS  # alias for clarity in incremental_runner
