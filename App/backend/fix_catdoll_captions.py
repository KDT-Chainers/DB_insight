"""fix_catdoll_captions.py — cat_doll_34/35 캡션 교정 + L1/L2/L3 npy 부분 재임베딩.

cat_doll_34: 회색 고양이 봉제인형 (카펫 위)
cat_doll_35: 검정&빨간 고양이 캐릭터 인형 (흰 배경, plaid hat, animal ears)

실행:
    cd App/backend
    python fix_catdoll_captions.py
"""
import sys, io, json, logging
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
from config import PATHS

import numpy as np

CACHE_DIR  = Path(PATHS["TRICHEF_IMG_CACHE"])
JSONL      = CACHE_DIR / "captions_triple.jsonl"
IDS_FILE   = CACHE_DIR / "img_ids.json"
CAPTION_DIR = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / ".." / ".." / "extracted_DB" / "Img" / "captions"
CAPTION_DIR = CAPTION_DIR.resolve()

TARGET_KEYS = [
    "영진_7차/cat_doll_34.jpg",
    "영진_7차/cat_doll_35.jpg",
]

NEW_CAPTIONS = {
    "영진_7차/cat_doll_34.jpg": {
        "L1": "회색 고양이 모양의 봉제 인형이 카펫에 누워 있다.",
        "L2": "봉제인형, stuffed cat, plush toy, 고양이 인형, gray cat, cat plush, 인형, cute, soft toy, 카펫, carpet",
        "L3": "회색 빛의 고양이 봉제 인형이 줄무늬 카펫 위에 편안하게 누워 있다. 부드럽고 포근한 털 소재로 만들어진 귀여운 고양이 인형으로, 스웨터 패턴의 복슬복슬한 모습이다. stuffed cat toy, gray cat plush, cute cat doll, soft toy, 봉제인형, 고양이 인형, plush cat, cat stuffed animal",
        "txt": "회색 고양이 봉제 인형이 줄무늬 카펫 위에 누워 있다. stuffed cat toy, plush cat doll.",
    },
    "영진_7차/cat_doll_35.jpg": {
        "L1": "고양이 귀를 가진 블랙 앤 레드 귀여운 캐릭터 인형이다.",
        "L2": "인형, cat doll, 고양이 인형, 고양이 귀, animal ears, doll, plush, toy, black hair, red, cute face, plaid hat, 캐릭터 인형, stuffed toy, figurine, 봉제인형, cat character",
        "L3": "흰색 배경 위에 놓인 검정과 빨간색의 귀여운 고양이 캐릭터 인형이다. 검은 긴 머리카락과 체크무늬 모자, 고양이 귀, 빨간 입술을 가진 앙증맞은 인형으로 섬세한 디테일과 부드러운 질감이 특징이다. cute black red cat doll, character doll, animal ears, plaid hat, toy figure, 인형, 고양이 인형, 캐릭터, doll head",
        "txt": "검정과 빨간색 고양이 캐릭터 인형. 고양이 귀, 체크무늬 모자, 빨간 입술. cute cat character doll, black red, animal ears.",
    },
}


def step1_update_jsonl():
    print("[1/3] captions_triple.jsonl 업데이트...")
    lines = JSONL.read_text(encoding="utf-8").splitlines()
    updated = 0
    new_lines = []
    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue
        try:
            obj = json.loads(line)
            norm = obj.get("rel", "").replace("\\", "/")
            matched = next((k for k in TARGET_KEYS if norm.endswith(k) or norm == k), None)
            if matched:
                cap = NEW_CAPTIONS[matched]
                obj["L1"] = cap["L1"]
                obj["L2"] = cap["L2"]
                obj["L3"] = cap["L3"]
                new_lines.append(json.dumps(obj, ensure_ascii=False))
                updated += 1
                print(f"  OK: {norm}")
            else:
                new_lines.append(line)
        except json.JSONDecodeError:
            new_lines.append(line)
    JSONL.write_text("\n".join(new_lines), encoding="utf-8")
    print(f"  -> {updated}개 업데이트 완료")


def step2_update_txt():
    print("[2/3] .txt 캡션 파일 업데이트...")
    for key, cap in NEW_CAPTIONS.items():
        stem = Path(key).stem  # cat_doll_34 / cat_doll_35
        txt_path = CAPTION_DIR / f"{stem}.txt"
        if txt_path.exists():
            txt_path.write_text(cap["txt"], encoding="utf-8")
            print(f"  OK: {txt_path.name}")
        else:
            print(f"  (없음) {txt_path}")


def step3_reembed_rows():
    print("[3/3] L1/L2/L3 npy 해당 행 재임베딩...")
    from embedders.trichef import bgem3_caption_im as im_embedder

    ids = json.loads(IDS_FILE.read_text("utf-8"))["ids"]

    # 대상 인덱스 탐색
    targets: list[tuple[int, str]] = []
    for i, img_id in enumerate(ids):
        norm = img_id.replace("\\", "/")
        for k in TARGET_KEYS:
            if norm.endswith(k) or norm == k:
                targets.append((i, k))
                break

    if not targets:
        print("  [ERROR] ids.json 에서 대상 항목 못 찾음")
        return

    # 각 레벨 텍스트 준비
    rows = [(idx, NEW_CAPTIONS[k]) for idx, k in targets]
    l1_texts = [cap["L1"] for _, cap in rows]
    l2_texts = [cap["L2"] for _, cap in rows]
    l3_texts = [cap["L3"] for _, cap in rows]

    print(f"  재임베딩 대상 인덱스: {[idx for idx, _ in rows]}")

    L1_new = im_embedder.embed_passage(l1_texts)
    L2_new = im_embedder.embed_passage(l2_texts)
    L3_new = im_embedder.embed_passage(l3_texts)

    for lvl, fname, new_vecs in [
        ("L1", "cache_img_Im_L1.npy", L1_new),
        ("L2", "cache_img_Im_L2.npy", L2_new),
        ("L3", "cache_img_Im_L3.npy", L3_new),
    ]:
        npy_path = CACHE_DIR / fname
        mat = np.load(npy_path).astype(np.float32)
        for j, (row_idx, _) in enumerate(rows):
            mat[row_idx] = new_vecs[j].astype(np.float32)
        np.save(npy_path, mat)
        print(f"  {lvl}: {fname} {len(rows)}개 행 업데이트 완료")

    print("  -> npy 재저장 완료")


if __name__ == "__main__":
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("=" * 60)
    print(f"cat_doll_34/35 캡션 교정 ({device})")
    print("=" * 60)
    step1_update_jsonl()
    step2_update_txt()
    step3_reembed_rows()
    print("=" * 60)
    print("완료. 백엔드 재시작 필요 (캐시 재로드).")
    print("=" * 60)
