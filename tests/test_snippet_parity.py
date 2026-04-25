"""tests/test_snippet_parity.py — App/MR snippet 의도적 복제본 동기화 검증.

App/backend/services/trichef/snippet.py 와 MR_TriCHEF/pipeline/snippet.py 는
도메인 격리 원칙상 의도적으로 복제 유지된다 (App 이 MR 패키지를 sys.path 에
가져오지 않음). 이 테스트는 두 사본이 시간이 지나며 어긋나는 drift 를 막는다.

검증 2축:
  (1) AST 동등성 — 함수 본문(docstring/주석/공백 제외)이 구조적으로 동일
  (2) 행동 동등성 — 한/영 corpus 12 케이스에서 동일 출력

도메인 격리 위반 0: 양쪽을 importlib 으로 파일 경로 직접 로드.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "App" / "backend" / "services" / "trichef" / "snippet.py"
MR_PATH  = ROOT / "MR_TriCHEF" / "pipeline" / "snippet.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"failed to spec {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def app_mod() -> ModuleType:
    return _load(APP_PATH, "_snippet_app")


@pytest.fixture(scope="module")
def mr_mod() -> ModuleType:
    return _load(MR_PATH, "_snippet_mr")


# ── (1) AST 동등성 ────────────────────────────────────────────────────────


def _extract_func_body_ast(path: Path, fname: str = "extract_best_snippet"):
    """함수 본문 AST 노드 리스트 반환 (docstring 제외)."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            body = node.body
            # 첫 번째 stmt 가 docstring(Expr→Constant str) 이면 제외
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            return body
    raise AssertionError(f"{fname} not found in {path}")


def _ast_dump(nodes) -> str:
    return "\n".join(
        ast.dump(n, annotate_fields=True, include_attributes=False) for n in nodes
    )


def test_ast_body_equivalence():
    """함수 본문 AST 가 docstring/주석/whitespace 제외하고 동일."""
    app_body = _extract_func_body_ast(APP_PATH)
    mr_body  = _extract_func_body_ast(MR_PATH)
    assert _ast_dump(app_body) == _ast_dump(mr_body), (
        "App/MR snippet 함수 본문 drift 감지 — "
        "한 쪽만 수정되었을 가능성. 양쪽 동기화 필요."
    )


def test_signature_equivalence():
    """함수 시그니처(인자명/기본값/반환 타입) 동일."""
    def _sig(path: Path) -> str:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "extract_best_snippet":
                return ast.dump(node.args) + "|" + ast.dump(node.returns or ast.Constant(None))
        raise AssertionError("not found")
    assert _sig(APP_PATH) == _sig(MR_PATH)


# ── (2) 행동 동등성 ───────────────────────────────────────────────────────

PARITY_CASES = [
    # (text, query, label)
    ("", "anything", "empty text"),
    ("   \n\t  ", "q", "whitespace only"),
    ("단일 문장입니다", "단일", "single sentence Korean"),
    ("Single sentence", "single", "single sentence English"),
    ("Hello world. Foo bar baz. The end.", "foo", "multi-sentence en, overlap"),
    ("Hello world. Foo bar baz. The end.", "zzz", "multi-sentence, no overlap"),
    ("문장1. 문장2. 검색 키워드 포함. 문장4.", "검색", "Korean period overlap"),
    ("문장1。문장2。검색 키워드。문장4。", "검색", "Korean fullwidth period"),
    ("Line one\nLine two with target\nLine three", "target", "newline split"),
    ("Mixed 문장 with English. 한글 query 검색.", "검색", "mixed lang"),
    ("a " * 500, "a", "very long, query=stopword-like"),
    ("UPPER lower MiXeD case Token. another sentence.", "token", "case-insensitive"),
    ("text without query overlap", "", "empty query"),
]


@pytest.mark.parametrize("text,query,label", PARITY_CASES)
def test_behavioral_parity(app_mod, mr_mod, text, query, label):
    a = app_mod.extract_best_snippet(text, query)
    m = mr_mod.extract_best_snippet(text, query)
    assert a == m, f"[{label}] App={a!r}  MR={m!r}"


def test_window_size_parity(app_mod, mr_mod):
    """window_size 인자 동작 일치."""
    long_text = "이것은 매우 긴 한 문장입니다 " * 100
    for w in (10, 50, 100, 220, 500):
        a = app_mod.extract_best_snippet(long_text, "긴", window_size=w)
        m = mr_mod.extract_best_snippet(long_text, "긴", window_size=w)
        assert a == m, f"window_size={w}: App={a!r}  MR={m!r}"
        assert len(a) <= w
