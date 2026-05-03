import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.query_expand import expand_bilingual

tests = [
    "entertainment award ceremony",
    "science physics quantum",
    "teacher consultation",
    "startup entrepreneurship",
    "연예대상 시상식",
    "과학 물리 양자역학",
    "상담 면담 선생님",
    "창업 스타트업",
    "soccer national team",
    "축구 국가대표",
]
for q in tests:
    exp = expand_bilingual(q)
    added = exp[len(q):].strip() if exp != q else "(no expansion)"
    print(f"{q!r}: +{added!r}")
