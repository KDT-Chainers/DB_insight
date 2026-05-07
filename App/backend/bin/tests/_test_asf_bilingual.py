"""Quick test: ASF bilingual query expansion works."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.trichef.asf_filter import _bilingual_expand, asf_scores

# Test bilingual expansion
test_queries = [
    "농구 경기",
    "basketball game",
    "선거 결과",
    "election results",
    "인공지능 기술",
    "artificial intelligence",
    "경제 성장",
    "economic growth",
]

print("=== Bilingual Expansion ===")
for q in test_queries:
    expanded = _bilingual_expand(q)
    print(f"  {q!r:30s} -> {expanded!r}")

# Test ASF scoring with bilingual tokens
print("\n=== ASF Cross-lingual Score Test ===")
# Simulate doc with Korean "농구" token (idf=3.5)
vocab_ko = {"농구": {"df": 2, "idf": 3.5}, "경기": {"df": 5, "idf": 2.8}, "축구": {"df": 3, "idf": 3.2}}
doc_sets_ko = [{"농구": 3.5, "경기": 2.8}, {"축구": 3.2}, {"경기": 2.8}]

# English query "basketball" should match Korean doc with "농구" via expansion
s = asf_scores("basketball", doc_sets_ko, vocab_ko)
print(f"  EN query 'basketball' vs KO doc ['농구','경기'] -> score={s[0]:.4f}  (expected > 0)")
print(f"  EN query 'basketball' vs KO doc ['축구']       -> score={s[1]:.4f}  (expected = 0)")

# Korean query "농구" should match as well
s2 = asf_scores("농구 경기", doc_sets_ko, vocab_ko)
print(f"  KO query '농구 경기' vs KO doc ['농구','경기']  -> score={s2[0]:.4f}  (expected = 1)")

# English doc, Korean query
vocab_en = {"basketball": {"df": 2, "idf": 3.5}, "game": {"df": 5, "idf": 2.1}}
doc_sets_en = [{"basketball": 3.5, "game": 2.1}, {"game": 2.1}]
s3 = asf_scores("농구 경기", doc_sets_en, vocab_en)
print(f"  KO query '농구 경기' vs EN doc ['basketball','game'] -> score={s3[0]:.4f}  (expected > 0)")
