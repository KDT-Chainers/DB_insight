"""파일명 → 가수·곡명 후보 추출.

music_search_20260422/filename_parse.py 포팅.
"Artist_Title.mp4", "Artist_Title_audio.mp3" 등 형식 지원.
"""
from __future__ import annotations

from pathlib import Path


def stem_without_audio_suffix(filename: str) -> str:
    stem = Path(filename).stem
    if stem.endswith("_audio"):
        return stem[: -len("_audio")]
    return stem


def guess_artist_title(filename: str) -> tuple[str, str]:
    """예: 'BTS_Dynamite.mp4' → ('BTS', 'Dynamite').
    underscore 없으면 ('', 전체 stem)."""
    base = stem_without_audio_suffix(filename)
    if "_" not in base:
        return ("", base.strip())
    artist, title = base.split("_", 1)
    return (artist.strip(), title.strip())
