# TRI-CHEF 사용자 매뉴얼

## 개요
TRI-CHEF(Tri-axis Complex Hermitian Engine for Files)는 DB_insight 에 통합된
3축 복소수 벡터 검색 엔진이다. 이미지(image)와 문서 페이지(doc_page) 두 도메인을
단일 인터페이스로 검색한다.

## 접속 방법
1. 앱 실행 후 좌측 사이드바 → **TRI-CHEF** 클릭
2. URL: `/trichef`

## 검색 예시 쿼리
| 카테고리 | 예시 쿼리 |
|---|---|
| 이미지 | "해변의 일몰", "도시 야경", "강아지 공원" |
| 문서 | "매출 차트 2023", "회의록 암호화", "프로젝트 일정표" |
| 복합 | "빨간색 그래프가 있는 보고서" |

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/trichef/search` | 검색 실행 |
| GET  | `/api/trichef/status` | 캐시 현황 조회 |
| POST | `/api/trichef/reindex` | 전체/부분 재임베딩 |
| GET  | `/api/trichef/file` | 파일 스트리밍 |
| GET  | `/api/trichef/image-tags` | 태그 JSON |

### POST /api/trichef/search
```json
{
  "query": "해변 사진",
  "topk": 10,
  "domains": ["image", "doc_page"]
}
```

### POST /api/trichef/reindex
```json
{ "scope": "all" }       // 전체
{ "scope": "image" }     // 이미지만
{ "scope": "document" }  // 문서만
```

## 재임베딩 절차

### 최초 임베딩 (raw_DB 데이터 배치 후)
```bash
cd App/backend
python -c "
from embedders.trichef.incremental_runner import run_image_incremental, run_doc_incremental
print(run_image_incremental())
print(run_doc_incremental())
"
```

### 증분 재임베딩 (파일 추가/수정 시)
동일 명령 재실행. SHA-256 해시 비교로 변경된 파일만 임베딩.

## 데이터 경로
```
Data/
├── raw_DB/
│   ├── Img/        ← 이미지 원본 (JPG/PNG/WEBP)
│   └── Docs/       ← 문서 원본 (PDF/DOCX/HWP/XLSX/TXT)
├── extracted_DB/
│   ├── Img/captions/   ← Qwen2.5-VL 캡션 캐시
│   └── Doc/page_images/ ← PDF 페이지 JPEG
└── embedded_DB/
    ├── Img/            ← 이미지 3축 .npy 캐시
    ├── Doc/            ← 문서 3축 .npy 캐시
    └── trichef/        ← TRI-CHEF 전용 ChromaDB
```

## 성능 목표 (레퍼런스 V23 Fix-6)
| 지표 | 목표 |
|---|---|
| Precision | ≥ 0.99 |
| Recall | ≥ 0.95 |
| F1 | ≥ 0.97 |
| True Negative Rate | 1.00 |

## 모델 요구사항
| 모델 | 용도 | VRAM |
|---|---|---|
| SigLIP2-SO400M | Re 축 (1152d) | ~3GB |
| multilingual-e5-large | Im 축 (1024d) | ~1GB |
| DINOv2-large | Z 축 (1024d) | ~1GB |
| Qwen2.5-VL-3B | 캡션 생성 + 쿼리 확장 | ~6GB |

CUDA 12.x + VRAM ≥ 8GB (동시 로딩 시 최대 12GB) 권장.
