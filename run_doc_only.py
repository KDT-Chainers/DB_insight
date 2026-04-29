"""Doc-only incremental reembedding (skip Img since 1,421/1,421 already done)."""
import io
import json
import logging
import os
import sys

# UTF-8 stdout (Windows cp949 우회)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

os.chdir(os.path.join(os.path.dirname(__file__), "App", "backend"))
sys.path.insert(0, os.getcwd())

log_path = os.path.join(os.path.dirname(__file__), "..", "reindex_doc.log")
log_path = os.path.abspath(log_path)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

from embedders.trichef.incremental_runner import run_doc_incremental

print("=== Doc incremental 시작 (논문/ 폴더 21개 추가) ===", flush=True)
r = run_doc_incremental()
print("Doc 결과:", r, flush=True)

out_path = os.path.join(os.path.dirname(__file__), "..", "reindex_doc_result.json")
out_path = os.path.abspath(out_path)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(r.__dict__, f, ensure_ascii=False, indent=2, default=str)
print("=== 완료. 결과:", out_path, "===", flush=True)
