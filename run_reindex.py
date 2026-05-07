"""TRI-CHEF 전체 재임베딩 실행 스크립트."""
import logging
import json
import sys
import os

os.chdir(os.path.join(os.path.dirname(__file__), "App", "backend"))
sys.path.insert(0, os.getcwd())

log_path = os.path.join(os.path.dirname(__file__), "reindex.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

from embedders.trichef.incremental_runner import run_image_incremental, run_doc_incremental

print("=== 이미지 재임베딩 시작 ===")
r1 = run_image_incremental()
print("이미지 결과:", r1)

print("=== 문서 재임베딩 시작 ===")
r2 = run_doc_incremental()
print("문서 결과:", r2)

result = {"image": r1.__dict__, "document": r2.__dict__}
out_path = os.path.join(os.path.dirname(__file__), "reindex_result.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("=== 완료. 결과:", out_path, "===")
