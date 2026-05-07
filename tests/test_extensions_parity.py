"""tests/test_extensions_parity.py — 3개 도메인 _extensions.py 모듈 동기화 검증.

도메인 격리(App/DI/MR 상호 import 금지) 를 유지하기 위해 같은 셋을 복제 보관.
이 테스트가 drift 를 자동 감지.

도메인 격리 위반 0: 모든 모듈을 importlib 으로 파일 경로 직접 로드.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, mod_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader, f"failed to spec {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── App / DI 동일성 검증 ────────────────────────────────────────────────────

def test_app_di_img_parity():
    app_mod = _load(ROOT / "App" / "backend" / "_extensions.py", "_app_ext_img")
    di_mod  = _load(ROOT / "DI_TriCHEF" / "_extensions.py",      "_di_ext_img")
    assert app_mod.IMG_EXTS == di_mod.IMG_EXTS, (
        f"IMG_EXTS drift — App: {sorted(app_mod.IMG_EXTS)}  DI: {sorted(di_mod.IMG_EXTS)}"
    )


def test_app_di_vid_parity():
    app_mod = _load(ROOT / "App" / "backend" / "_extensions.py", "_app_ext_vid")
    di_mod  = _load(ROOT / "DI_TriCHEF" / "_extensions.py",      "_di_ext_vid")
    assert app_mod.VID_EXTS == di_mod.VID_EXTS, (
        f"VID_EXTS drift — App: {sorted(app_mod.VID_EXTS)}  DI: {sorted(di_mod.VID_EXTS)}"
    )


def test_app_di_aud_parity():
    app_mod = _load(ROOT / "App" / "backend" / "_extensions.py", "_app_ext_aud")
    di_mod  = _load(ROOT / "DI_TriCHEF" / "_extensions.py",      "_di_ext_aud")
    assert app_mod.AUD_EXTS == di_mod.AUD_EXTS, (
        f"AUD_EXTS drift — App: {sorted(app_mod.AUD_EXTS)}  DI: {sorted(di_mod.AUD_EXTS)}"
    )


def test_app_di_doc_parity():
    app_mod = _load(ROOT / "App" / "backend" / "_extensions.py", "_app_ext_doc")
    di_mod  = _load(ROOT / "DI_TriCHEF" / "_extensions.py",      "_di_ext_doc")
    assert app_mod.DOC_EXTS == di_mod.DOC_EXTS, (
        f"DOC_EXTS drift — App: {sorted(app_mod.DOC_EXTS)}  DI: {sorted(di_mod.DOC_EXTS)}"
    )


def test_app_di_image_embed_exts_parity():
    """IMAGE_EMBED_EXTS alias 도 동일해야 함."""
    app_mod = _load(ROOT / "App" / "backend" / "_extensions.py", "_app_ext_iee")
    di_mod  = _load(ROOT / "DI_TriCHEF" / "_extensions.py",      "_di_ext_iee")
    assert app_mod.IMAGE_EMBED_EXTS == di_mod.IMAGE_EMBED_EXTS, (
        f"IMAGE_EMBED_EXTS drift — App: {sorted(app_mod.IMAGE_EMBED_EXTS)}  "
        f"DI: {sorted(di_mod.IMAGE_EMBED_EXTS)}"
    )


# ── MR ⊆ App 부분집합 검증 ──────────────────────────────────────────────────

def test_mr_movie_subset_of_app_video():
    """MR_TriCHEF.MOVIE_EXTS 는 App.VID_EXTS 의 부분집합이어야 함 (확장 시 양쪽 동기화)."""
    app_mod = _load(ROOT / "App" / "backend" / "_extensions.py",          "_app_ext_mv")
    mr_mod  = _load(ROOT / "MR_TriCHEF" / "pipeline" / "_extensions.py", "_mr_ext_mv")
    extra = mr_mod.MOVIE_EXTS - app_mod.VID_EXTS
    assert not extra, (
        f"MR MOVIE_EXTS 가 App VID_EXTS 보다 더 많은 ext 보유: {sorted(extra)}"
    )


def test_mr_music_subset_of_app_audio():
    """MR_TriCHEF.MUSIC_EXTS 는 App.AUD_EXTS 의 부분집합이어야 함 (확장 시 양쪽 동기화)."""
    app_mod = _load(ROOT / "App" / "backend" / "_extensions.py",          "_app_ext_ms")
    mr_mod  = _load(ROOT / "MR_TriCHEF" / "pipeline" / "_extensions.py", "_mr_ext_ms")
    extra = mr_mod.MUSIC_EXTS - app_mod.AUD_EXTS
    assert not extra, (
        f"MR MUSIC_EXTS 가 App AUD_EXTS 보다 더 많은 ext 보유: {sorted(extra)}"
    )
