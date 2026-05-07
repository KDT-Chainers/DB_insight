# MIGRATION: Test-DB_Secretary → DB_insight (TRI-CHEF Document + Image)

> **목적**: `Test-DB_Secretary`에서 완성된 TRI-CHEF 3축 복소수 검색 엔진(document + image 도메인)을
> 본 `DB_insight` 프로젝트의 Flask + React/Electron + ChromaDB 아키텍처로 이식한다.
>
> **범위**: 이 문서 하나로 포팅 전체 과정을 재현할 수 있어야 한다. 모든 코드 스니펫, 디렉토리 배치,
> 재임베딩 명령, UI 연결까지 포함한다. 누락된 것이 보이면 곧바로 이 문서를 갱신한다.
>
> **대상 브랜치**: `feature/trichef-port` (아래 §11 브랜치 전략 참조)
>
> **작성 기준일**: 2026-04-22
>
> **상위 레퍼런스 경로**: `C:\yssong\KDT-FT-team3-Chainers\Test-DB_Secretary\`
> (이하 `<REF>` 로 축약)

---

## 0. 한 장 요약

| 항목 | 값 |
|---|---|
| 이식 대상 도메인 | document (doc_text + doc_page) + image |
| 신규 모델 | SigLIP2-SO400M (Re 1152d), multilingual-e5-large (Im 1024d, caption), DINOv2-large (Z 1024d), Qwen2.5-VL-3B (쿼리 확장 + 캡션) |
| 신규 아키텍처 | 3축 Gram-Schmidt 직교화 + Hermitian 내적 + LangGraph 12-node + Data-adaptive calibration |
| 백엔드 접점 | Flask blueprint `routes/trichef.py` @ port 5001 → `/api/trichef/*` |
| 프론트엔드 접점 | React 신규 page `TriChefSearch.jsx` + `SearchSidebar` 에 탭 추가 |
| 데이터 영향 | `Data/embedded_DB/Doc/`, `Data/embedded_DB/Img/` **전면 재생성**. 기존 MiniLM/e5 캐시와 공존 가능 (컬렉션 분리) |
| 성능 목표 (레퍼런스) | image: P=0.9949, R=0.9512, F1=0.9726, TNR=1.00 (V23 Fix-6, 612 쿼리) |
| 재임베딩 시간 (RTX 3090급) | 약 60~90분 (이미지 1~2천장 + 문서 수백 페이지) |
| API 비용 | 0 (모든 모델 로컬 GPU) |

---

## 1. 왜 이 포팅이 필요한가

### 1.1 현 DB_insight 한계
- `embedders/doc.py`, `embedders/image.py`가 **동일한 384d MiniLM**만 사용 → 이미지/문서 간 교차 의미 파악 부족
- 단일 벡터 cosine 유사도 기반 → **할루시네이션 제거 메커니즘 없음** (`"DB에 없는 것"` 거부 불가)
- `SearchEndpoint /api/search`는 단순 top-K ChromaDB query → 랭킹/재정렬/임계값 없음

### 1.2 TRI-CHEF 도입 효과 (Test-DB_Secretary 실측)
| 지표 | 기존 단일 CLIP | TRI-CHEF V23 Fix-6 |
|---|---:|---:|
| Precision | 0.864 | **0.9949** |
| Recall | - | **0.9512** |
| F1 | 0.864 | **0.9726** |
| 할루시 건 (612 쿼리) | 39 | **2** |
| True Negative Rate | 0.00 | **1.00** |

### 1.3 기술 핵심
- **3축 복소수 벡터**: `Re + i·Im⊥ + j·Z⊥⊥` (Re=Vision, Im=Caption text, Z=Self-supervised)
- **Gram-Schmidt 직교화**: 세 축이 서로 독립된 정보 채널이 되도록 투영 제거
- **Data-adaptive threshold**: `abs_thr = μ_null + Φ⁻¹(1−FAR)·σ_null` (데이터셋 확장마다 자동 재보정)
- **12-node LangGraph**: prefilter → hermitian → accept → zgate → adaptive → ensemble → reeval → accept/reject
- **Qwen2.5-VL 쿼리 확장**: paraphrase n=3 → 벡터 평균 → L2 정규화 (할루시 무증가 증명됨)

---

## 2. 현 DB_insight 아키텍처 매핑

```
DB_insight/
├── App/
│   ├── frontend/           React 18 + Vite + Electron, 6 pages
│   │   └── src/pages/MainSearch.jsx   ← TRI-CHEF 탭 여기에 통합
│   └── backend/            Flask + ChromaDB
│       ├── app.py          포트 5001, CORS
│       ├── config.py       경로 상수 (PATHS.RAW, PATHS.EXTRACTED, PATHS.EMBEDDED)
│       ├── routes/         5 blueprints
│       │   ├── auth.py
│       │   ├── search.py   ← 기존 /api/search 유지, 별도 blueprint 추가
│       │   ├── index.py
│       │   ├── files.py
│       │   └── history.py
│       ├── embedders/      doc, video, image, audio (모두 MiniLM 384d)
│       └── db/             vector_store.py (ChromaDB wrapper, 타입별 client)
└── Data/
    ├── raw_DB/             원본 파일 (placeholder)
    ├── extracted_DB/{Doc,Img,Movie,Rec}/  중간 결과 (caption.txt, chunks.json)
    └── embedded_DB/{Doc,Img,Movie,Rec}/   .npy 캐시 + chroma.sqlite3
```

**공존 원칙**: 기존 `files_doc` / `files_image` 컬렉션은 그대로 두고, TRI-CHEF 용 신규 컬렉션
`trichef_doc_text`, `trichef_doc_page`, `trichef_image` 를 추가한다. 사용자가 기존/신규를
선택해서 검색할 수 있도록 한다.

---

## 3. 목표 아키텍처 (포팅 완료 후)

```
 ┌─────────────────────────────────────────────────────────────┐
 │  React/Electron UI                                          │
 │   MainSearch.jsx ─▶ [기존 검색] / [TRI-CHEF 검색] 탭 전환   │
 │   TriChefSearch.jsx ─▶ POST /api/trichef/search             │
 │   결과: 이미지 썸네일 + doc_text 미리보기 + doc_page 미리보기│
 │         per-domain μ/σ/abs_thr 표시                          │
 └─────────────────────────────────────────────────────────────┘
                        │
                        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Flask 5001                                                  │
 │   routes/trichef.py  (신규 blueprint)                        │
 │     • POST /api/trichef/search   — 3 도메인 병렬 검색        │
 │     • GET  /api/trichef/file?path=...  — 안전 경로 스트리밍  │
 │     • GET  /api/trichef/image-tags     — 태그 JSON 서빙      │
 │     • POST /api/trichef/reindex        — 전체 재임베딩       │
 │                                                              │
 │   services/trichef/                 (신규 패키지)             │
 │     ├── unified_engine.py     ← TRI-CHEF 검색 엔진            │
 │     ├── graph_12node.py       ← LangGraph 노드 정의           │
 │     ├── qwen_expand.py        ← Qwen2.5-VL 쿼리 확장          │
 │     ├── tri_gs.py             ← Gram-Schmidt 직교화 수학       │
 │     ├── calibration.py        ← μ_null / σ_null / abs_thr      │
 │     └── cat_affinity.py       ← Hard-Neg 카테고리 거부 필터    │
 │                                                              │
 │   embedders/trichef/                (신규 패키지)              │
 │     ├── siglip2_re.py         ← SigLIP2-SO400M (1152d)         │
 │     ├── e5_caption_im.py      ← e5-large on caption (1024d)    │
 │     ├── dinov2_z.py           ← DINOv2-large (1024d)           │
 │     ├── qwen_caption.py       ← 이미지 자동 캡션 (Qwen2.5-VL)  │
 │     ├── doc_page_render.py    ← PDF/DOCX → JPEG 페이지 렌더    │
 │     └── incremental_runner.py ← IndexRegistry + 증분 빌드       │
 └─────────────────────────────────────────────────────────────┘
                        │
                        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Data                                                        │
 │   raw_DB/{Doc,Img}/                    원본 파일              │
 │   extracted_DB/Doc/{page_images,captions,chunks}/             │
 │   extracted_DB/Img/{captions,tags}/                           │
 │   embedded_DB/Doc/                                            │
 │     ├── cache_doc_Re_siglip2.npy       (N, 1152)              │
 │     ├── cache_doc_Im_e5cap.npy         (N, 1024)              │
 │     ├── cache_doc_Z_dinov2.npy         (N, 1024)              │
 │     ├── doc_ids.json                                           │
 │     └── calibration_doc.json                                   │
 │   embedded_DB/Img/                                            │
 │     ├── cache_img_Re_siglip2.npy       (M, 1152)              │
 │     ├── cache_img_Im_e5cap.npy         (M, 1024)              │
 │     ├── cache_img_Z_dinov2.npy         (M, 1024)              │
 │     ├── img_ids.json                                           │
 │     ├── image_tags.json                                        │
 │     └── calibration_img.json                                   │
 │   embedded_DB/chroma.sqlite3           (기존 + 신규 컬렉션)    │
 └─────────────────────────────────────────────────────────────┘
```

---

## 4. 의존성 추가 (`requirements.txt`)

기존 requirements 에 아래 라인을 **추가**한다 (중복 허용됨, pip 가 처리):

```txt
# --- TRI-CHEF 추가 의존성 ---
open-clip-torch>=2.24          # SigLIP2 로더
timm>=1.0                      # DINOv2-large 래퍼
pdfminer.six                   # PDF 텍스트 + 좌표
pymupdf>=1.24                  # PDF → JPEG 페이지 렌더 (PyMuPDF)
python-docx                    # DOCX 텍스트/이미지
openpyxl                       # XLSX
olefile                        # HWP 기초 파서
langgraph>=0.2                 # LangGraph 12-node
scipy                          # 통계 calibration (선택)
tqdm                           # 진행률
accelerate                     # HF 모델 device_map
```

설치:
```bash
cd C:\yssong\KDT-FT-team3-Chainers\DB_insight\App\backend
pip install -r requirements.txt
```

**GPU 요구**: CUDA 12.x + VRAM ≥8GB (SigLIP2 + DINOv2 + Qwen2.5-VL-3B 동시 로딩 시 최대 12GB).
CPU-only 환경은 권장하지 않음 (1회 재임베딩이 수 시간 → 수일 단위).

---

## 5. `config.py` 확장

`App/backend/config.py` 에 아래 상수를 추가한다 (기존 PATHS/CFG dict 뒤):

```python
# ─────────────────────────────────────────────────────────────
# TRI-CHEF 설정 (포팅 후 추가)
# ─────────────────────────────────────────────────────────────
import os

TRICHEF_CFG = {
    # 모델 ID (HuggingFace)
    "MODEL_RE_SIGLIP2":   "google/siglip2-so400m-patch16-naflex",
    "MODEL_IM_E5LARGE":   "intfloat/multilingual-e5-large",
    "MODEL_Z_DINOV2":     "facebook/dinov2-large",
    "MODEL_QWEN_VL":      "Qwen/Qwen2.5-VL-3B-Instruct",

    # 벡터 차원 (모델 결정값, 수정 금지)
    "DIM_RE": 1152,
    "DIM_IM": 1024,
    "DIM_Z":  1024,

    # FAR / 임계값 (Data-adaptive 재보정이 덮어씀)
    "FAR_IMG":      0.20,   # 완화: 더 많은 TP 통과
    "FAR_DOC_TEXT": 0.05,   # 엄격
    "FAR_DOC_PAGE": 0.05,   # 엄격

    # 쿼리 확장
    "EXPAND_QUERY_ENABLED": True,
    "EXPAND_QUERY_N": 3,

    # 배치
    "BATCH_IMG": 64,
    "BATCH_TXT": 128,

    # 디바이스
    "DEVICE": "cuda" if os.environ.get("FORCE_CPU") != "1" else "cpu",

    # 컬렉션명 (기존 files_doc/files_image 와 분리)
    "COL_DOC_TEXT": "trichef_doc_text",
    "COL_DOC_PAGE": "trichef_doc_page",
    "COL_IMAGE":    "trichef_image",

    # Hard-Neg Cat-Affinity 마진
    "CAT_HN_MARGIN": 0.02,

    # LangGraph
    "GRAPH_MAX_ITER": 3,
    "GRAPH_HI_MARGIN": 0.030,
    "GRAPH_HN_MARGIN": 0.020,
}

# 경로 (PATHS 에 편의 필드 추가)
PATHS["TRICHEF_IMG_CACHE"]  = os.path.join(PATHS["EMBEDDED_DB"], "Img")
PATHS["TRICHEF_DOC_CACHE"]  = os.path.join(PATHS["EMBEDDED_DB"], "Doc")
PATHS["TRICHEF_IMG_EXTRACT"] = os.path.join(PATHS["EXTRACTED_DB"], "Img")
PATHS["TRICHEF_DOC_EXTRACT"] = os.path.join(PATHS["EXTRACTED_DB"], "Doc")

for p in (
    PATHS["TRICHEF_IMG_CACHE"], PATHS["TRICHEF_DOC_CACHE"],
    PATHS["TRICHEF_IMG_EXTRACT"], PATHS["TRICHEF_DOC_EXTRACT"],
    os.path.join(PATHS["TRICHEF_IMG_EXTRACT"], "captions"),
    os.path.join(PATHS["TRICHEF_IMG_EXTRACT"], "tags"),
    os.path.join(PATHS["TRICHEF_DOC_EXTRACT"], "page_images"),
    os.path.join(PATHS["TRICHEF_DOC_EXTRACT"], "captions"),
    os.path.join(PATHS["TRICHEF_DOC_EXTRACT"], "chunks"),
):
    os.makedirs(p, exist_ok=True)
```

---

## 6. 임베더 모듈 (embedders/trichef/)

### 6.1 `siglip2_re.py` — Re 축 임베더

레퍼런스: `<REF>\scripts\build_siglip2_re_cache.py`

DB_insight 포트:
```python
"""embedders/trichef/siglip2_re.py — Re 축 (SigLIP2-SO400M 1152d).

이미지와 텍스트 양쪽을 동일 공간에 임베딩하여 cross-modal 코사인 유사도를 얻는다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

from ...config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = TRICHEF_CFG["MODEL_RE_SIGLIP2"]
_DEVICE   = TRICHEF_CFG["DEVICE"]
_BATCH    = TRICHEF_CFG["BATCH_IMG"]

_model: AutoModel | None = None
_proc:  AutoProcessor | None = None


def _load() -> None:
    global _model, _proc
    if _model is not None:
        return
    logger.info(f"[siglip2_re] 모델 로드: {_MODEL_ID} on {_DEVICE}")
    _proc  = AutoProcessor.from_pretrained(_MODEL_ID)
    _model = AutoModel.from_pretrained(
        _MODEL_ID,
        torch_dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
    ).to(_DEVICE).eval()


@torch.inference_mode()
def embed_images(paths: list[Path]) -> np.ndarray:
    """(N, 1152) L2-normalized float32."""
    _load()
    out: list[np.ndarray] = []
    for i in range(0, len(paths), _BATCH):
        batch = [Image.open(p).convert("RGB") for p in paths[i:i+_BATCH]]
        inp = _proc(images=batch, return_tensors="pt").to(_DEVICE)
        vec = _model.get_image_features(**inp)
        vec = torch.nn.functional.normalize(vec, dim=-1)
        out.append(vec.cpu().float().numpy())
        if _DEVICE == "cuda":
            torch.cuda.empty_cache()
    return np.vstack(out).astype(np.float32)


@torch.inference_mode()
def embed_texts(texts: list[str]) -> np.ndarray:
    """쿼리 또는 캡션을 SigLIP2 text encoder 로 임베딩."""
    _load()
    out: list[np.ndarray] = []
    B = TRICHEF_CFG["BATCH_TXT"]
    for i in range(0, len(texts), B):
        inp = _proc(text=texts[i:i+B], padding="max_length",
                    truncation=True, return_tensors="pt").to(_DEVICE)
        vec = _model.get_text_features(**inp)
        vec = torch.nn.functional.normalize(vec, dim=-1)
        out.append(vec.cpu().float().numpy())
    return np.vstack(out).astype(np.float32)
```

### 6.2 `e5_caption_im.py` — Im 축 임베더

레퍼런스: `<REF>\backend\embeddings\e5_large_embedder.py`

```python
"""embedders/trichef/e5_caption_im.py — Im 축 (multilingual-e5-large 1024d).

이미지/문서 페이지의 캡션 텍스트를 e5 로 임베딩하여 Im 축으로 사용.
"""
from __future__ import annotations

import logging

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from ...config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = TRICHEF_CFG["MODEL_IM_E5LARGE"]
_DEVICE   = TRICHEF_CFG["DEVICE"]

_tok = None
_model = None


def _load():
    global _tok, _model
    if _model is not None:
        return
    logger.info(f"[e5_im] 모델 로드: {_MODEL_ID}")
    _tok   = AutoTokenizer.from_pretrained(_MODEL_ID)
    _model = AutoModel.from_pretrained(
        _MODEL_ID,
        torch_dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
    ).to(_DEVICE).eval()


def _encode(texts: list[str], prefix: str) -> np.ndarray:
    _load()
    B = TRICHEF_CFG["BATCH_TXT"]
    out: list[np.ndarray] = []
    for i in range(0, len(texts), B):
        batch = [f"{prefix}: {t}" for t in texts[i:i+B]]
        inp = _tok(batch, padding=True, truncation=True,
                   max_length=512, return_tensors="pt").to(_DEVICE)
        with torch.inference_mode():
            hid = _model(**inp).last_hidden_state
            mask = inp["attention_mask"].unsqueeze(-1).float()
            emb = (hid * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            emb = torch.nn.functional.normalize(emb, dim=-1)
        out.append(emb.cpu().float().numpy())
    return np.vstack(out).astype(np.float32)


def embed_passage(texts: list[str]) -> np.ndarray:
    return _encode(texts, "passage")


def embed_query(texts: list[str]) -> np.ndarray:
    return _encode(texts, "query")
```

### 6.3 `dinov2_z.py` — Z 축 임베더

레퍼런스: `<REF>\scripts\z_embedder.py`

```python
"""embedders/trichef/dinov2_z.py — Z 축 (DINOv2-large 1024d, self-supervised)."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

from ...config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = TRICHEF_CFG["MODEL_Z_DINOV2"]
_DEVICE   = TRICHEF_CFG["DEVICE"]
_BATCH    = TRICHEF_CFG["BATCH_IMG"]

_model = None
_proc  = None


def _load():
    global _model, _proc
    if _model is not None:
        return
    logger.info(f"[dinov2_z] 모델 로드: {_MODEL_ID}")
    _proc  = AutoImageProcessor.from_pretrained(_MODEL_ID)
    _model = AutoModel.from_pretrained(
        _MODEL_ID,
        torch_dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
    ).to(_DEVICE).eval()


@torch.inference_mode()
def embed_images(paths: list[Path]) -> np.ndarray:
    _load()
    out: list[np.ndarray] = []
    for i in range(0, len(paths), _BATCH):
        batch = [Image.open(p).convert("RGB") for p in paths[i:i+_BATCH]]
        inp = _proc(images=batch, return_tensors="pt").to(_DEVICE)
        out_d = _model(**inp)
        # [CLS] 토큰 (N, 1024)
        vec = out_d.last_hidden_state[:, 0]
        vec = torch.nn.functional.normalize(vec, dim=-1)
        out.append(vec.cpu().float().numpy())
        if _DEVICE == "cuda":
            torch.cuda.empty_cache()
    return np.vstack(out).astype(np.float32)
```

### 6.4 `qwen_caption.py` — 이미지 캡션 생성

레퍼런스: `<REF>\backend\search\qwen_vl.py`

```python
"""embedders/trichef/qwen_caption.py — Qwen2.5-VL-3B 로 이미지 캡션 + 쿼리 확장."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

from ...config import TRICHEF_CFG

logger = logging.getLogger(__name__)

_MODEL_ID = TRICHEF_CFG["MODEL_QWEN_VL"]
_DEVICE   = TRICHEF_CFG["DEVICE"]
_lock = threading.Lock()
_model = None
_proc  = None


def _load():
    global _model, _proc
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        logger.info(f"[qwen] 모델 로드: {_MODEL_ID}")
        _proc  = AutoProcessor.from_pretrained(_MODEL_ID)
        _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            _MODEL_ID,
            torch_dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
            device_map=_DEVICE,
        ).eval()


@torch.inference_mode()
def caption(image_path: Path, max_new: int = 64) -> str:
    _load()
    img = Image.open(image_path).convert("RGB")
    msg = [{"role": "user", "content": [
        {"type": "image", "image": img},
        {"type": "text",  "text": "이 이미지의 핵심 객체와 장면을 1문장으로 한국어 설명."},
    ]}]
    text = _proc.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
    inp = _proc(text=[text], images=[img], padding=True, return_tensors="pt").to(_DEVICE)
    out = _model.generate(**inp, max_new_tokens=max_new, do_sample=False)
    gen = _proc.batch_decode(out[:, inp.input_ids.shape[1]:],
                              skip_special_tokens=True)[0].strip()
    return gen


@torch.inference_mode()
def paraphrase(query: str, n: int = 3, max_new: int = 48) -> list[str]:
    _load()
    prompt = (
        f"다음 검색 쿼리를 의미가 같지만 표현이 다른 {n}개 문장으로 바꿔 한 줄씩 출력:\n"
        f"[쿼리] {query}"
    )
    msg = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    text = _proc.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
    inp = _proc(text=[text], padding=True, return_tensors="pt").to(_DEVICE)
    out = _model.generate(**inp, max_new_tokens=max_new, do_sample=False)
    gen = _proc.batch_decode(out[:, inp.input_ids.shape[1]:],
                              skip_special_tokens=True)[0]
    lines = [l.strip("-•* ").strip() for l in gen.splitlines() if l.strip()]
    return [l for l in lines if l][:n]
```

### 6.5 `doc_page_render.py` — 문서 → 페이지 이미지

레퍼런스: `<REF>\backend\indexing\doc_extractor.py` 중 PDF 렌더 부분

```python
"""embedders/trichef/doc_page_render.py — PDF/DOCX → JPEG 페이지 이미지."""
from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from ...config import PATHS

logger = logging.getLogger(__name__)
PAGE_DIR = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_images"


def render_pdf(pdf_path: Path, dpi: int = 110) -> list[Path]:
    """PDF 의 각 페이지를 JPEG 로 저장. 리턴: [페이지 이미지 경로...]"""
    doc_id = pdf_path.stem
    out_dir = PAGE_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    with fitz.open(pdf_path) as d:
        for i, page in enumerate(d):
            out = out_dir / f"p{i:04d}.jpg"
            if out.exists():
                results.append(out)
                continue
            pix = page.get_pixmap(dpi=dpi)
            pix.save(out)
            results.append(out)
    logger.info(f"[render_pdf] {pdf_path.name} → {len(results)}장")
    return results
```

### 6.6 `incremental_runner.py` — 증분 빌드 오케스트레이터

레퍼런스: `<REF>\scripts\build_yj2_incremental_cache.py` + `<REF>\backend\db\index_registry.py`

```python
"""embedders/trichef/incremental_runner.py — 증분 임베딩 러너.

IndexRegistry 에 저장된 파일 SHA-256 해시를 비교하여 신규/수정 파일만 임베딩한다.
3축 캐시 (.npy) 누적 append + ChromaDB upsert + calibration 재보정 트리거.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from tqdm import tqdm

from ...config import PATHS, TRICHEF_CFG
from ...db.vector_store import VectorStore       # 기존 모듈 사용
from . import siglip2_re, e5_caption_im, dinov2_z, qwen_caption, doc_page_render
from ..trichef import tri_gs, calibration

logger = logging.getLogger(__name__)


@dataclass
class IncrementalResult:
    domain: str
    new: int
    existing: int
    total: int


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_registry(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_registry(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 이미지 도메인 ────────────────────────────────────────────────────────────
def run_image_incremental() -> IncrementalResult:
    raw_dir = Path(PATHS["RAW_DB"]) / "Img"
    cache_dir = Path(PATHS["TRICHEF_IMG_CACHE"])
    reg_path  = cache_dir / "registry.json"
    registry  = _load_registry(reg_path)

    img_files = sorted(
        p for p in raw_dir.rglob("*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    existing_ids = list(registry.keys())
    new_files: list[Path] = []
    for p in img_files:
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        sha = _sha256(p)
        if registry.get(key, {}).get("sha") != sha:
            new_files.append(p)
            registry[key] = {"sha": sha, "abs": str(p)}

    logger.info(f"[img_inc] 기존={len(existing_ids)}, 신규={len(new_files)}")
    if not new_files:
        return IncrementalResult("image", 0, len(existing_ids), len(existing_ids))

    # 1. 캡션 생성 (Im 축 원천)
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    captions: list[str] = []
    for p in tqdm(new_files, desc="Qwen caption"):
        cp = cap_dir / f"{p.stem}.txt"
        if cp.exists():
            captions.append(cp.read_text(encoding="utf-8"))
        else:
            c = qwen_caption.caption(p)
            cp.write_text(c, encoding="utf-8")
            captions.append(c)

    # 2. 3축 임베딩
    new_Re = siglip2_re.embed_images(new_files)
    new_Im = e5_caption_im.embed_passage(captions)
    new_Z  = dinov2_z.embed_images(new_files)

    # 3. 누적 concat
    def _merge(name: str, new_vec: np.ndarray) -> np.ndarray:
        p = cache_dir / name
        if p.exists():
            prev = np.load(p)
            merged = np.vstack([prev, new_vec])
        else:
            merged = new_vec
        np.save(p, merged)
        return merged

    Re_all = _merge("cache_img_Re_siglip2.npy", new_Re)
    Im_all = _merge("cache_img_Im_e5cap.npy",   new_Im)
    Z_all  = _merge("cache_img_Z_dinov2.npy",   new_Z)

    # ids 파일 갱신
    ids_path = cache_dir / "img_ids.json"
    prev_ids = _load_registry(ids_path).get("ids", []) if ids_path.exists() else []
    new_ids  = [str(p.relative_to(raw_dir)).replace("\\", "/") for p in new_files]
    all_ids  = prev_ids + new_ids
    ids_path.write_text(json.dumps({"ids": all_ids}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # 4. Gram-Schmidt 직교화 + ChromaDB upsert
    Im_perp, Z_perp = tri_gs.orthogonalize(Re_all, Im_all, Z_all)
    _upsert_chroma(TRICHEF_CFG["COL_IMAGE"], all_ids, Re_all, Im_perp, Z_perp, raw_dir)

    # 5. calibration 재보정
    calibration.calibrate_domain("image", Re_all, Im_perp, Z_perp)

    # 6. registry save
    _save_registry(reg_path, registry)

    return IncrementalResult("image", len(new_files),
                             len(existing_ids), len(all_ids))


def _upsert_chroma(collection: str, ids: list[str],
                    Re: np.ndarray, Im_perp: np.ndarray, Z_perp: np.ndarray,
                    src_root: Path) -> None:
    """ChromaDB 에 Re||Im⊥||Z⊥⊥ concat 벡터로 upsert.
    ChromaDB 는 단일 벡터만 지원하므로 실제 Hermitian 연산은 서버 측에서
    .npy 원본을 직접 읽는다. ChromaDB 는 빠른 prefilter 용으로만 사용.
    """
    store = VectorStore(collection)
    docs = [{"path": str(src_root / i), "id": i} for i in ids]
    embeds = np.hstack([Re, Im_perp, Z_perp]).astype(np.float32)   # (N, 3200)
    store.upsert(ids, embeds.tolist(), docs)


# ── 문서 도메인 (doc_text + doc_page) ────────────────────────────────────────
def run_doc_incremental() -> IncrementalResult:
    raw_dir = Path(PATHS["RAW_DB"]) / "Doc"
    cache_dir = Path(PATHS["TRICHEF_DOC_CACHE"])
    reg_path = cache_dir / "registry.json"
    registry = _load_registry(reg_path)

    doc_files = sorted(
        p for p in raw_dir.rglob("*")
        if p.suffix.lower() in {".pdf", ".docx", ".hwp", ".xlsx", ".txt"}
    )

    new_docs = [p for p in doc_files
                if registry.get(str(p.relative_to(raw_dir)).replace("\\", "/"),
                                {}).get("sha") != _sha256(p)]
    logger.info(f"[doc_inc] 기존={len(registry)}, 신규={len(new_docs)}")

    if not new_docs:
        return IncrementalResult("document", 0, len(registry), len(registry))

    # 1. PDF → 페이지 JPEG 렌더 (doc_page 소스)
    all_page_imgs: list[Path] = []
    all_page_captions: list[str] = []
    for p in tqdm(new_docs, desc="PDF render + caption"):
        if p.suffix.lower() != ".pdf":
            continue   # docx/hwp 처리는 확장 포인트 (아래 §13 참조)
        pages = doc_page_render.render_pdf(p)
        cap_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "captions" / p.stem
        cap_dir.mkdir(parents=True, exist_ok=True)
        for pg in pages:
            cp = cap_dir / f"{pg.stem}.txt"
            if cp.exists():
                cap = cp.read_text(encoding="utf-8")
            else:
                cap = qwen_caption.caption(pg)
                cp.write_text(cap, encoding="utf-8")
            all_page_imgs.append(pg)
            all_page_captions.append(cap)

    # 2. 3축 임베딩 (doc_page)
    new_Re = siglip2_re.embed_images(all_page_imgs)
    new_Im = e5_caption_im.embed_passage(all_page_captions)
    new_Z  = dinov2_z.embed_images(all_page_imgs)

    # 3. 캐시 누적
    def _merge(name: str, new_vec: np.ndarray) -> np.ndarray:
        p = cache_dir / name
        if p.exists():
            prev = np.load(p); merged = np.vstack([prev, new_vec])
        else:
            merged = new_vec
        np.save(p, merged); return merged

    Re_all = _merge("cache_doc_page_Re.npy", new_Re)
    Im_all = _merge("cache_doc_page_Im.npy", new_Im)
    Z_all  = _merge("cache_doc_page_Z.npy",  new_Z)

    # 4. ids 갱신
    ids_path = cache_dir / "doc_page_ids.json"
    prev = _load_registry(ids_path).get("ids", []) if ids_path.exists() else []
    new_ids = [str(pg.relative_to(Path(PATHS["TRICHEF_DOC_EXTRACT"])))
               .replace("\\", "/") for pg in all_page_imgs]
    all_ids = prev + new_ids
    ids_path.write_text(json.dumps({"ids": all_ids}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    Im_perp, Z_perp = tri_gs.orthogonalize(Re_all, Im_all, Z_all)
    _upsert_chroma(TRICHEF_CFG["COL_DOC_PAGE"], all_ids, Re_all, Im_perp, Z_perp,
                   Path(PATHS["TRICHEF_DOC_EXTRACT"]))
    calibration.calibrate_domain("doc_page", Re_all, Im_perp, Z_perp)

    # 5. TODO: doc_text 파이프라인 — 아래 §6.7 참조 (청킹 + e5 passage)
    #         초기 포팅에서는 doc_page 만으로 시작해도 좋다.

    # 6. registry save
    for p in new_docs:
        key = str(p.relative_to(raw_dir)).replace("\\", "/")
        registry[key] = {"sha": _sha256(p), "abs": str(p)}
    _save_registry(reg_path, registry)

    return IncrementalResult("document", len(new_docs),
                             len(registry), len(registry))
```

### 6.7 `doc_text` 청크 파이프라인 (옵션 확장)

- PDF 에서 텍스트 추출 → 1000자 청크 → e5-large passage 임베딩 → ChromaDB `trichef_doc_text`.
- Re 축은 **없다**. Im 축만 존재하는 특수 케이스 → 1D cosine 으로 처리.
- 레퍼런스: `<REF>\backend\indexing\doc_chunker.py`, `<REF>\backend\indexing\doc_indexer.py`
- 초기 포팅에서는 건너뛰고, `doc_page` 가 안정화된 후 2차 작업으로 추가 권장.

---

## 7. services/trichef/ — 검색 런타임

### 7.1 `tri_gs.py`

```python
"""services/trichef/tri_gs.py — Tri Gram-Schmidt 직교화."""
import numpy as np


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.clip(n, 1e-12, None)


def orthogonalize(Re: np.ndarray, Im: np.ndarray, Z: np.ndarray
                  ) -> tuple[np.ndarray, np.ndarray]:
    """Re → Im⊥ → Z⊥⊥ 순차 투영 제거.

    Im 과 Z 가 Re 보다 차원이 클 수 있으므로 내적 전에 **공간 일치화** 필요.
    Test-DB_Secretary 는 SVD 로 최소 차원 프로젝션 후 직교화한다.
    여기서는 안전하게 normalize → projection coefficient 제거만 수행.
    (Im, Z 차원이 Re 와 달라도 각자 내부에서 L2 norm 이 맞춰져 있기 때문)
    """
    Re_hat = _norm(Re)
    # Im⊥ (Im 차원이 Re 와 다르면 직접 투영 불가 — scalar projection 으로 근사)
    # 실제 CLAUDE.md V10 구현은 Im 과 Re 차원을 맞추기 위해
    # Im ← Im @ projector(Re_dim → Im_dim) 를 했으나 DB_insight 포트에서는
    # **같은 차원(1152 vs 1024 vs 1024)이므로 동일 공간 내적 불가**
    # → 대신 각자 내부에서 L2 normalize 만 수행하고 Gram-Schmidt 는 스킵.
    Im_hat = _norm(Im)
    Z_hat  = _norm(Z)
    return Im_hat, Z_hat


def hermitian_score(q_Re: np.ndarray, q_Im: np.ndarray, q_Z: np.ndarray,
                    d_Re: np.ndarray, d_Im: np.ndarray, d_Z: np.ndarray,
                    alpha: float = 0.4, beta: float = 0.2) -> np.ndarray:
    """3축 복소수 내적: |A + i·α·B + j·β·C|.

    - A = Re_q · Re_d (cross-modal, 가장 강한 신호)
    - B = Im_q · Im_d (caption 텍스트 의미 일치)
    - C = Z_q  · Z_d  (self-supervised 시각 일관성)
    α, β 는 보조축 가중치. 디폴트 0.4 / 0.2 로 시작 → calibration 후 조정.
    """
    A = q_Re @ d_Re.T
    B = q_Im @ d_Im.T
    C = q_Z  @ d_Z.T
    return np.sqrt(A**2 + (alpha*B)**2 + (beta*C)**2)
```

### 7.2 `calibration.py`

```python
"""services/trichef/calibration.py — Data-adaptive abs_threshold 재보정.

각 도메인별로 null 분포(무관 쿼리→DB 점수)를 추정하여
abs_thr = μ_null + Φ⁻¹(1−FAR)·σ_null 을 저장한다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ...config import PATHS, TRICHEF_CFG
from . import tri_gs


_CALIB_PATH = Path(PATHS["EMBEDDED_DB"]) / "calibration.json"


def _acklam_inv_phi(p: float) -> float:
    """표준정규 분위수의 Acklam 근사 (scipy 없이)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [ 7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2*math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) \
               / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= ph:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q \
               / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2*math.log(1-p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) \
            / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def calibrate_domain(domain: str, Re: np.ndarray,
                     Im_perp: np.ndarray, Z_perp: np.ndarray) -> dict:
    """도메인 내 self-score 분포를 추정해 abs_threshold 저장.

    Null 분포 ≈ 서로 다른 ID 간 cross-score. N_sample 1000 쌍을 랜덤 추출.
    """
    N = Re.shape[0]
    rng = np.random.default_rng(42)
    pairs = 1000
    i_idx = rng.integers(0, N, pairs)
    j_idx = rng.integers(0, N, pairs)
    mask = i_idx != j_idx
    i_idx = i_idx[mask]; j_idx = j_idx[mask]

    scores = tri_gs.hermitian_score(
        Re[i_idx], Im_perp[i_idx], Z_perp[i_idx],
        Re[j_idx], Im_perp[j_idx], Z_perp[j_idx],
    ).diagonal()
    mu   = float(scores.mean())
    sig  = float(scores.std())
    FAR  = TRICHEF_CFG[f"FAR_{'IMG' if domain=='image' else ('DOC_TEXT' if domain=='doc_text' else 'DOC_PAGE')}"]
    thr  = mu + _acklam_inv_phi(1 - FAR) * sig

    data = _load_all()
    data[domain] = {
        "mu_null": mu, "sigma_null": sig,
        "abs_threshold": thr, "far": FAR,
        "N": N,
    }
    _CALIB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return data[domain]


def _load_all() -> dict:
    if _CALIB_PATH.exists():
        return json.loads(_CALIB_PATH.read_text(encoding="utf-8"))
    return {}


def get_thresholds(domain: str) -> dict:
    return _load_all().get(domain, {"mu_null": 0.0, "sigma_null": 1.0,
                                     "abs_threshold": 0.5})
```

### 7.3 `qwen_expand.py` — 쿼리 확장 래퍼

```python
"""services/trichef/qwen_expand.py — 쿼리 paraphrase + 벡터 평균."""
from __future__ import annotations

import logging

import numpy as np

from ...config import TRICHEF_CFG
from ..embedders.trichef import qwen_caption

logger = logging.getLogger(__name__)


def expand(query: str) -> list[str]:
    if not TRICHEF_CFG["EXPAND_QUERY_ENABLED"]:
        return [query]
    try:
        variants = qwen_caption.paraphrase(query, n=TRICHEF_CFG["EXPAND_QUERY_N"])
    except Exception as e:
        logger.warning(f"[expand] Qwen 실패 ({e}) — 원본만")
        return [query]
    q_norm = query.strip()
    seen = {q_norm}
    dedup: list[str] = []
    for v in variants:
        v = v.strip()
        if v and v not in seen:
            seen.add(v); dedup.append(v)
    return [query] + dedup[: TRICHEF_CFG["EXPAND_QUERY_N"]]


def avg_normalize(vecs: np.ndarray) -> np.ndarray:
    if vecs.ndim == 1:
        v = vecs.astype(np.float32)
    else:
        v = vecs.astype(np.float32).mean(axis=0)
    n = float(np.linalg.norm(v))
    return v / (n + 1e-12)
```

### 7.4 `unified_engine.py` — 핵심 검색 엔진

```python
"""services/trichef/unified_engine.py — 3 도메인 검색 통합 엔진.

Search flow: query → expand → 3축 쿼리 임베딩 → Hermitian → threshold → top-K.
간단 버전 (LangGraph 없이 single-shot). LangGraph 확장은 §7.5 참조.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ...config import PATHS, TRICHEF_CFG
from ..embedders.trichef import siglip2_re, e5_caption_im
from . import calibration, qwen_expand, tri_gs

logger = logging.getLogger(__name__)


@dataclass
class TriChefResult:
    id: str
    score: float
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


class TriChefEngine:
    """3축 복소수 검색 엔진. 이미지/문서 양쪽 재사용 가능."""

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        # 이미지
        idir = Path(PATHS["TRICHEF_IMG_CACHE"])
        if (idir / "cache_img_Re_siglip2.npy").exists():
            self._cache["image"] = {
                "Re":    np.load(idir / "cache_img_Re_siglip2.npy"),
                "Im":    np.load(idir / "cache_img_Im_e5cap.npy"),
                "Z":     np.load(idir / "cache_img_Z_dinov2.npy"),
                "ids":   json.loads((idir / "img_ids.json").read_text(encoding="utf-8"))["ids"],
            }
        # 문서 페이지
        ddir = Path(PATHS["TRICHEF_DOC_CACHE"])
        if (ddir / "cache_doc_page_Re.npy").exists():
            self._cache["doc_page"] = {
                "Re":  np.load(ddir / "cache_doc_page_Re.npy"),
                "Im":  np.load(ddir / "cache_doc_page_Im.npy"),
                "Z":   np.load(ddir / "cache_doc_page_Z.npy"),
                "ids": json.loads((ddir / "doc_page_ids.json").read_text(encoding="utf-8"))["ids"],
            }
        logger.info(f"[engine] 캐시 로드 완료: {list(self._cache.keys())}")

    def _embed_query(self, query: str) -> tuple[np.ndarray, np.ndarray]:
        variants = qwen_expand.expand(query)
        q_Re = qwen_expand.avg_normalize(siglip2_re.embed_texts(variants))
        q_Im = qwen_expand.avg_normalize(e5_caption_im.embed_query(variants))
        return q_Re, q_Im

    def search(self, query: str, domain: str, topk: int = 20) -> list[TriChefResult]:
        if domain not in self._cache:
            logger.warning(f"[engine] 도메인 {domain} 캐시 없음")
            return []
        q_Re, q_Im = self._embed_query(query)
        d = self._cache[domain]
        # Z 쿼리 는 없음 → Im 을 fallback (Z 기여도는 DB 내부 일관성으로만 사용)
        q_Z = q_Im  # 근사 (성능 최적화 시 DINOv2 text encoder 없으므로 이대로)
        scores = tri_gs.hermitian_score(
            q_Re[None, :], q_Im[None, :], q_Z[None, :],
            d["Re"], d["Im"], d["Z"],
        )[0]                                            # (N,)
        cal = calibration.get_thresholds(domain)
        abs_thr = cal["abs_threshold"]
        mu, sig = cal["mu_null"], cal["sigma_null"]
        order = np.argsort(-scores)
        out: list[TriChefResult] = []
        for i in order[: topk * 2]:
            s = float(scores[i])
            if s < abs_thr:
                continue
            z = (s - mu) / max(sig, 1e-9)
            conf = 0.5 * (1 + _erf(z / (2**0.5)))
            out.append(TriChefResult(
                id=d["ids"][i], score=s, confidence=conf,
                metadata={"domain": domain},
            ))
            if len(out) >= topk:
                break
        return out


def _erf(x: float) -> float:
    # Abramowitz & Stegun 7.1.26
    import math
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    s = 1 if x >= 0 else -1
    x = abs(x)
    t = 1 / (1 + p*x)
    y = 1 - ((((a5*t + a4)*t + a3)*t + a2)*t + a1)*t * math.exp(-x*x)
    return s * y
```

### 7.5 `graph_12node.py` — LangGraph 12-node (확장, 선택)

초기 포팅에서는 7.4 single-shot 으로 시작하고, 12-node 그래프는 2차 작업으로 추가.
풀 구현은 `<REF>\scripts\image_v23_langgraph.py` 를 참고해서 옮긴다.

---

## 8. Flask Blueprint — `routes/trichef.py`

```python
"""routes/trichef.py — TRI-CHEF REST API."""
from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from ..config import PATHS, TRICHEF_CFG
from ..services.trichef.unified_engine import TriChefEngine
from ..embedders.trichef.incremental_runner import (
    run_image_incremental, run_doc_incremental,
)

logger = logging.getLogger(__name__)
bp = Blueprint("trichef", __name__, url_prefix="/api/trichef")

_engine: TriChefEngine | None = None


def _get_engine() -> TriChefEngine:
    global _engine
    if _engine is None:
        _engine = TriChefEngine()
    return _engine


@bp.post("/search")
def search():
    body = request.get_json(force=True)
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"error": "query 필수"}), 400
    topk = int(body.get("topk", 20))
    domains = body.get("domains", ["image", "doc_page"])

    engine = _get_engine()
    all_items: list[dict] = []
    stats: dict = {"per_domain": {}}
    from ..services.trichef import calibration
    for d in domains:
        try:
            res = engine.search(query, domain=d, topk=topk)
        except Exception as e:
            logger.exception(f"domain={d} 실패")
            stats["per_domain"][d] = {"error": str(e)[:200], "count": 0}
            continue
        cal = calibration.get_thresholds(d)
        stats["per_domain"][d] = {
            "count": len(res),
            "mu_null": round(cal["mu_null"], 4),
            "sigma_null": round(cal["sigma_null"], 4),
            "abs_threshold": round(cal["abs_threshold"], 4),
        }
        for rank, r in enumerate(res, 1):
            all_items.append({
                "rank": rank, "domain": d,
                "id": r.id, "score": round(r.score, 4),
                "confidence": round(r.confidence, 4),
                "preview_url": f"/api/trichef/file?domain={d}&path={r.id}",
            })
    all_items.sort(key=lambda x: -x["confidence"])
    top = all_items[: topk]
    for i, it in enumerate(top, 1):
        it["global_rank"] = i
    return jsonify({
        "query": query,
        "top": top,
        "stats": stats,
    })


_SAFE_ROOTS = [
    Path(PATHS["RAW_DB"]),
    Path(PATHS["EXTRACTED_DB"]),
    Path(PATHS["EMBEDDED_DB"]),
]


@bp.get("/file")
def serve_file():
    rel = request.args.get("path", "")
    domain = request.args.get("domain", "image")
    if not rel:
        return jsonify({"error": "path 필수"}), 400
    if domain == "image":
        candidate = Path(PATHS["RAW_DB"]) / "Img" / rel
    else:
        candidate = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / rel
    candidate = candidate.resolve()
    if not any(candidate == r.resolve() or candidate.is_relative_to(r.resolve())
               for r in _SAFE_ROOTS):
        return jsonify({"error": "허용되지 않은 경로"}), 403
    if not candidate.exists():
        return jsonify({"error": "파일 없음"}), 404
    mime, _ = mimetypes.guess_type(str(candidate))
    return send_file(str(candidate), mimetype=mime or "application/octet-stream")


@bp.post("/reindex")
def reindex():
    body = request.get_json(silent=True) or {}
    scope = body.get("scope", "all")   # "image" | "document" | "all"
    results = {}
    if scope in ("image", "all"):
        results["image"] = run_image_incremental().__dict__
    if scope in ("document", "all"):
        results["document"] = run_doc_incremental().__dict__
    global _engine
    _engine = None   # 재로드 강제
    return jsonify(results)


@bp.get("/image-tags")
def image_tags():
    p = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "tags" / "image_tags.json"
    if not p.exists():
        return jsonify({"count": 0, "images": []})
    import json as _json
    data = _json.loads(p.read_text(encoding="utf-8"))
    return jsonify({"count": len(data), "images": data})
```

`app.py` 에 blueprint 등록:
```python
# App/backend/app.py  (기존 blueprint 등록 아래 추가)
from .routes.trichef import bp as trichef_bp
app.register_blueprint(trichef_bp)
```

---

## 9. React 프론트엔드 — `TriChefSearch.jsx`

`App/frontend/src/pages/TriChefSearch.jsx` 신규 생성:
```jsx
import { useState } from "react";
import { API_BASE } from "../api";

export default function TriChefSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState(null);

  async function runSearch() {
    if (!query.trim()) return;
    setLoading(true); setResults(null); setStats(null);
    try {
      const r = await fetch(`${API_BASE}/api/trichef/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query, topk: 10,
          domains: ["image", "doc_page"],
        }),
      });
      const j = await r.json();
      setResults(j.top);
      setStats(j.stats);
    } finally { setLoading(false); }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">TRI-CHEF 통합 검색</h1>
      <div className="flex gap-2 mb-6">
        <input value={query} onChange={e => setQuery(e.target.value)}
               onKeyDown={e => e.key === "Enter" && runSearch()}
               placeholder="자연어로 검색…"
               className="flex-1 px-4 py-2 border rounded" />
        <button onClick={runSearch} disabled={loading}
                className="px-6 py-2 bg-blue-600 text-white rounded disabled:opacity-50">
          {loading ? "검색 중…" : "검색"}
        </button>
      </div>

      {stats && (
        <div className="mb-4 text-sm text-gray-600">
          {Object.entries(stats.per_domain).map(([d, s]) => (
            <span key={d} className="mr-4">
              <b>{d}</b>: {s.count}건 (μ={s.mu_null} σ={s.sigma_null} thr={s.abs_threshold})
            </span>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {results?.map(it => (
          <div key={`${it.domain}-${it.id}`} className="border rounded p-2">
            <div className="text-xs text-gray-500">
              #{it.global_rank} · {it.domain} · conf={it.confidence}
            </div>
            <img src={`${API_BASE}${it.preview_url}`}
                 alt={it.id}
                 className="w-full h-40 object-cover mt-1" />
            <div className="text-xs mt-1 truncate">{it.id}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

`App/frontend/src/App.jsx` 라우팅 추가:
```jsx
import TriChefSearch from "./pages/TriChefSearch";
// ...
<Route path="/trichef" element={<TriChefSearch />} />
```

`SearchSidebar.jsx` 메뉴에 `/trichef` 링크 추가.

---

## 10. 재임베딩 실행 절차

### 10.1 데이터 배치
```
Data/raw_DB/
├── Img/              — JPG/PNG/WEBP 원본 (하위 카테고리 폴더 자유)
└── Doc/              — PDF/DOCX/HWP/XLSX/TXT 원본
```

### 10.2 최초 전체 임베딩
```bash
cd C:\yssong\KDT-FT-team3-Chainers\DB_insight\App\backend

# 한 번에
python -c "from embedders.trichef.incremental_runner import run_image_incremental, run_doc_incremental; print(run_image_incremental()); print(run_doc_incremental())"
```

또는 REST:
```bash
# 백엔드 기동 후
curl -X POST http://localhost:5001/api/trichef/reindex -H "Content-Type: application/json" -d "{\"scope\":\"all\"}"
```

### 10.3 증분 재임베딩 (원본 추가/수정 시)
동일 명령 재실행. IndexRegistry SHA-256 비교로 **변경된 파일만** 임베딩.

### 10.4 예상 시간/리소스
| 원본 규모 | 이미지 | 문서 (페이지 렌더 포함) |
|---|---|---|
| 100개 | ~3분 | ~10분 |
| 1,000개 | ~20분 | ~60분 |
| 5,000개 | ~90분 | ~4시간 |

VRAM 피크: 이미지 6GB / 문서 (Qwen2.5-VL 포함) 10GB.

---

## 11. 브랜치 전략 & 커밋 가이드

### 11.1 브랜치
```bash
cd C:\yssong\KDT-FT-team3-Chainers\DB_insight
git checkout -b feature/trichef-port
```

### 11.2 권장 커밋 순서
| # | 커밋 메시지 | 파일 |
|---|---|---|
| 1 | chore: TRI-CHEF 의존성 추가 | requirements.txt |
| 2 | feat: TRI-CHEF config 상수 + 디렉토리 | App/backend/config.py |
| 3 | feat: Re/Im/Z 임베더 모듈 | App/backend/embedders/trichef/*.py |
| 4 | feat: Qwen 캡션 + 쿼리 확장 | embedders/trichef/qwen_caption.py, services/trichef/qwen_expand.py |
| 5 | feat: Gram-Schmidt + calibration | services/trichef/tri_gs.py, calibration.py |
| 6 | feat: 증분 임베딩 러너 | embedders/trichef/incremental_runner.py |
| 7 | feat: 통합 검색 엔진 | services/trichef/unified_engine.py |
| 8 | feat: Flask blueprint /api/trichef/* | routes/trichef.py, app.py 등록 |
| 9 | feat: React TriChefSearch 페이지 | frontend/src/pages/TriChefSearch.jsx |
| 10 | docs: 사용자 매뉴얼 + 예시 쿼리 | Docs/Knowledge/trichef_usage.md |

### 11.3 PR 체크리스트
- [ ] `pip install -r requirements.txt` 성공
- [ ] `python -c "from App.backend.embedders.trichef import siglip2_re"` 성공
- [ ] `python App/backend/app.py` 기동 (포트 5001) 정상
- [ ] `Data/raw_DB/Img/` 에 샘플 1~10장 넣고 `/api/trichef/reindex` 호출 성공
- [ ] `Data/embedded_DB/Img/cache_img_Re_siglip2.npy` 생성 확인
- [ ] `/api/trichef/search` 로 쿼리 `"해변"` 호출 → 결과 반환
- [ ] React `/trichef` 페이지에서 썸네일 + μ/σ/thr 표시 확인
- [ ] 기존 `/api/search` 엔드포인트 무영향 (regression 없음)

---

## 12. 검증 방법

### 12.1 유닛 확인
```python
# 1. 3축 임베딩 차원
from embedders.trichef import siglip2_re, e5_caption_im, dinov2_z
from pathlib import Path
p = Path("Data/raw_DB/Img/sample.jpg")
assert siglip2_re.embed_images([p]).shape == (1, 1152)
assert e5_caption_im.embed_passage(["해변"]).shape == (1, 1024)
assert dinov2_z.embed_images([p]).shape == (1, 1024)
```

### 12.2 E2E 스모크 (PowerShell)
레퍼런스: `<REF>\_smoke_test_8001.ps1` 을 5001 포트로 복사 + 엔드포인트 수정.

### 12.3 성능 기준선
- 이미지 50장 기준: Top-1 평균 score ≥ 0.85, abs_thr ≥ μ + 6σ
- doc_page 50 페이지 기준: Top-1 평균 score ≥ 0.70 (문서는 σ_null 크므로 score 낮아도 z_top 보존)

---

## 13. 한계 & 차후 확장 포인트

### 13.1 포팅 시 단순화한 부분
1. **Gram-Schmidt 근사화**: Re(1152d) vs Im/Z(1024d) 차원 불일치로 정규화만 수행 (§7.1 주석).
   완전 GS 원하면 Re 를 SVD/projection 으로 1024d 로 투영해야 함. Test-DB_Secretary 실측 잔차율 0.999 → DB_insight 에서도 동일 결과 기대.
2. **Z 쿼리 축**: DINOv2 는 text encoder 없음 → 쿼리 Z 를 Im 으로 근사. 성능 소폭 저하 가능 (CLAUDE.md V10 대비 -0.01 F1 추정).
3. **doc_text 도메인 제외**: 초기 포팅은 doc_page 만. doc_text 청킹 + e5 passage 파이프라인은 v2 로 추가.
4. **LangGraph 12-node 생략**: §7.4 single-shot 으로 시작. v2 에서 n4~n10 노드 추가.

### 13.2 v2 작업 목록
- [ ] doc_text 청킹 파이프라인 (1000자 + overlap)
- [ ] LangGraph 12-node 그래프 (prefilter → hermitian → zgate → adaptive → ensemble → reeval → accept/reject)
- [ ] Cat-Affinity Hard-Neg Test (Test-DB_Secretary V4 S11)
- [ ] Bivector Discriminant n5b (V25, off by default)
- [ ] React 갤러리 페이지 (image_tags.json 기반 태그 필터)

### 13.3 퍼포먼스 주의
- ChromaDB 에 `concat(Re||Im⊥||Z⊥⊥)` 3200d 벡터를 upsert 하지만 **실제 검색에서는 쓰지 않음** (§6.7 주석). Chroma 는 빠른 prefilter 용. 메인 점수는 .npy 원본으로 Hermitian 계산.
- 5만 이미지 초과 시 .npy 로드 메모리 고려 (Re+Im+Z = 50000 × (1152+1024+1024) × 4byte ≈ 640MB). 그 이상은 memmap 도입.

---

## 14. 참고 파일 매핑 (Test-DB_Secretary ↔ DB_insight)

| Test-DB_Secretary | DB_insight 신규 경로 | 비고 |
|---|---|---|
| `scripts/build_siglip2_re_cache.py` | `embedders/trichef/siglip2_re.py` + `incremental_runner.py` | 모듈화 |
| `scripts/build_dinov2_large_z_cache.py` | `embedders/trichef/dinov2_z.py` | 동일 로직 |
| `backend/embeddings/e5_large_embedder.py` | `embedders/trichef/e5_caption_im.py` | passage/query prefix |
| `backend/search/qwen_vl.py` | `embedders/trichef/qwen_caption.py` | paraphrase + caption |
| `scripts/rebuild_unified_chromadb.py` | `incremental_runner.py::_upsert_chroma` | 인라인화 |
| `scripts/calibrate_unified_chef.py` | `services/trichef/calibration.py` | 단순화 |
| `scripts/image_v23_langgraph.py` | (v2) `services/trichef/graph_12node.py` | 2차 작업 |
| `backend/search/unified_trichef.py` | `services/trichef/unified_engine.py` | 핵심 |
| `backend/api/routes_trichef.py` | `routes/trichef.py` | FastAPI→Flask |
| `backend/static/trichef.html` | `frontend/src/pages/TriChefSearch.jsx` | React 로 재작성 |

---

## 15. 질의 응답

**Q1. 이 MD 파일만으로 충분한가?**
A. 마스터 스펙으로 충분하되, §6~9 의 Python/JSX 스니펫을 **그대로 복사**해 파일로 저장하는 보조 작업이 필요하다. 각 섹션 코드 블록 상단에 파일 경로를 명시해두었다.

**Q2. 기존 ChromaDB 데이터는 지워야 하는가?**
A. 아니다. 기존 컬렉션(`files_doc`, `files_image`, `files_video`, `files_audio`)은 건드리지 말고 신규 컬렉션(`trichef_*`)만 추가한다. 사용자가 UI 에서 토글로 선택.

**Q3. `Data/raw_DB/` 가 placeholder 라고 되어 있는데?**
A. TRI-CHEF 도입 후에는 **raw_DB 가 실제 원본 저장소** 가 된다. 사용자가 배치하는 위치를 `Data/raw_DB/Img/` 와 `Data/raw_DB/Doc/` 로 고정한다.

**Q4. 브랜치에서 작업 중 main 에서 긴급 수정이 오면?**
A. `git merge main` 또는 `git rebase main` 으로 동기화. 이 포팅은 **신규 파일 추가 위주**이므로 충돌 위험이 거의 없다. 충돌 위험 있는 파일은 `app.py` (blueprint 등록 한 줄), `requirements.txt` (뒤에 추가), `frontend/src/App.jsx` (라우트 한 줄), `config.py` (뒤에 추가).

**Q5. 완료 후 Test-DB_Secretary 는 폐기해도 되나?**
A. 완전한 검증(성능 지표 재현, 1주일 운영 안정성) 전에는 유지. `Test-DB_Secretary` 는 **레퍼런스 구현** 으로 두고, DB_insight 가 **프로덕션** 경로가 되도록 점진 전환.

---

---

## 16. 포팅 후 개선 로그 (v2 / v3, 2026-04-22)

### 16.1 적용된 개선 (feature/trichef-port)

| 단계 | 내용 | 커밋 |
|---|---|---|
| v2 P1 | Im 축을 e5-large → **BGE-M3 Dense** 로 교체, BLIP 3-stage 캡션 (L1/L2/L3) | — |
| v2 P1-B | `doc_ingest` 도입: docx/doc/pptx/xlsx/odt/**hwp/hwpx**/txt/md/csv/html 지원 | — |
| v2 P2 | **BGE-M3 Sparse (XLM-R vocab 250002d)** + Dense/Sparse RRF (k=60, pool=200) | — |
| PDF text | PyMuPDF 로 페이지 원문 추출 → sparse 결합, 한글 lexical nnz 20× 증가 | ab08ef0 |
| v3 P3 | 도메인 **auto_vocab** (image 492 / doc 15000, DF·IDF, 한/영 stopwords) | d5bc90e |
| v3 P4 | **ASF 필터** (쿼리↔문서 어휘 오버랩, IDF 가중, 한글 compound substring 확장) → 3채널 RRF | 07067ec |
| Calibration | doc-doc self 대신 **랜덤 쿼리 null 분포** 로 abs_threshold 재추정 (0.96→0.21). `incremental_runner` 자동 calibration 제거로 덮어쓰기 방지 | ba56926, c05b45e |
| E2E | Dense / +Sparse / +ASF 3 구성 비교 스크립트 | 1fca760 |
| API | `POST /api/trichef/search` 에 `use_lexical/use_asf/pool` 파라미터 + `dense/lexical/asf` 메타데이터 응답 (후방호환) | c05b45e |

**현재 인덱스 규모:** 이미지 1743장 · 문서 422건 (PDF+docx+hwp+hwpx) → doc_page 34170장. sparse nnz 6.13M.

**E2E (6 쿼리 × 3 구성):** dense 0.333 · dense+sparse 0.333 · **dense+sp+asf 0.417** (+25% precision).

### 16.2 설치 요구사항

1. **Python 3.12** · **Node.js LTS** · **Git** · **NVIDIA GPU 드라이버 + CUDA 12.x**
2. **LibreOffice 26.2.2** — office/hwp 계열 PDF 변환
3. **Eclipse Temurin JRE 21** — LibreOffice 확장 실행용
4. **H2Orestart (.oxt)** — LibreOffice 확장, .hwp/.hwpx 지원
   ```powershell
   winget install TheDocumentFoundation.LibreOffice
   winget install EclipseAdoptium.Temurin.21.JRE
   # H2Orestart: https://github.com/ebandal/H2Orestart/releases/latest
   "C:\Program Files\LibreOffice\program\unopkg.exe" add H2Orestart.oxt
   ```
5. HuggingFace 모델 (첫 실행 자동 다운로드, ~15GB): `siglip2-so400m`, `bge-m3`, `dinov2-large`, `blip-image-captioning-large`

### 16.3 재빌드 순서 (증분 인덱싱 후)

```powershell
# 1. 증분 인덱싱 (image / doc)
python -c "from embedders.trichef.incremental_runner import run_doc_incremental; print(run_doc_incremental())"
# 2. 문서 sparse 재빌드 (PDF 원문 포함)
python DI_TriCHEF/scripts/rebuild_doc_sparse_with_text.py
# 3. 도메인 vocab & ASF 토큰셋 재빌드
python DI_TriCHEF/scripts/build_auto_vocab.py
python DI_TriCHEF/scripts/build_asf_token_sets.py
# 4. 쿼리 기반 calibration 재추정
python scripts/recalibrate_query_null.py
# 5. (선택) E2E 재평가
python scripts/e2e_eval.py
```

### 16.4 보류 항목

- 페이지 레벨 prune (source 삭제 시 .npy/sparse/asf_sets 물리 정리 — 현재 registry 만 정리)
- 이미지 한글 캡션 번역 (Dense 성능 충분으로 사용자 보류 결정)
- ColBERT 리랭커 (불필요 확정)
- `.exe` 배포 부트스트래퍼 (별도 작업)

---

**문서 끝. 작성자: Claude (Sonnet/Opus) · 2026-04-22 · 버전 1.1 (v2/v3 개선 로그 추가)**
