"""SSOT for MR_TriCHEF Movie/Music 도메인의 지원 파일 확장자.

도메인 격리 원칙: App/DI 모듈은 이 파일을 import 하지 않음.
tests/test_extensions_parity.py 가 MR.MOVIE_EXTS ⊆ App.VID_EXTS 와
MR.MUSIC_EXTS ⊆ App.AUD_EXTS 부분집합 관계를 검증.
"""
from __future__ import annotations

# Movie (ffmpeg)
MOVIE_EXTS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv",
    ".flv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts",
})

# Music (ffmpeg + soundfile)
MUSIC_EXTS: frozenset[str] = frozenset({
    ".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg",
    ".wma", ".opus", ".aiff", ".aif", ".amr",
})
