# `scripts/` — App 도메인 (Img/Doc) 운영·유지보수 스크립트

> **소유권**: 이 폴더는 **App 도메인 (Image / Document) 전용** 입니다.
> Movie/Music 스크립트는 `MR_TriCHEF/scripts/`, 알고리즘 벤치는
> `DI_TriCHEF/scripts/` 에 있습니다.

---

## 실행 전제 (Conventions)

- **CWD**: 반드시 프로젝트 루트 `DB_insight/` 에서 실행.
  ```bat
  cd C:\...\DB_insight
  python scripts\xxx.py
  ```
- **경로 기준**: `Path(__file__).parent.parent` 를 프로젝트 루트로 가정하는
  스크립트 다수. 폴더 이동 시 전부 재계산 필요.
- **sys.path**: 대부분 `sys.path.insert(0, "App/backend")` 로 App 패키지 진입.
- **인코딩**: Windows 에서는 `set PYTHONIOENCODING=utf-8` 권장 (cp949 회피).

---

## 파일 목록 (역할별)

### 빌드 / 인덱스 재구축
| 파일 | 역할 |
|---|---|
| `build_asf_token_sets.py` | 문서별 vocab-token 집합 precompute (v3 P4) |
| `build_auto_vocab.py` | image/doc 도메인 자동 어휘 사전 빌드 (v3 P3) |
| `build_sparse_index.py` | BGE-M3 Sparse 인덱스 빌드 (v2 P2) |
| `rebuild_im_axis.py` | Im 축 e5-large → BGE-M3 Dense 재구축 |
| `rebuild_doc_sparse_with_text.py` | PDF 원문 포함 sparse 재구축 |
| `finalize_doc_reindex.py` | .npy → ChromaDB upsert + registry 저장 복구 |

### 마이그레이션 / 복구 (일회성)
| 파일 | 역할 |
|---|---|
| `migrate_stem_hash.py` | H-2: page_images/captions → hash-suffix stem 이관 |
| `fix_registry_encoding.py` | registry.json 한글 깨짐 복구 |

### calibration
| 파일 | 역할 |
|---|---|
| `recalibrate_query_null.py` | 쿼리 기반 null 분포 재보정 (μ_null/σ_null/p95) |

### 벤치 / E2E
| 파일 | 역할 |
|---|---|
| `e2e_eval.py` | 3채널 통합 E2E 품질 평가 |
| `perf_benchmark.py` | 파이프라인 성능/품질 벤치마크 |
| `smoke_hybrid.py` | v2 P2 Dense / Sparse / Hybrid 비교 |
| `smoke_search.py` | v1 baseline E2E 검증 |

### 자동화 (장기 실행)
| 파일 | 역할 |
|---|---|
| `watchdog_img_caption_then_finalize.py` | Img 3-stage caption 완료 polling → 후속 2단계 자동 실행 |

---

## 이동하지 않은 이유 (Phase 3 리팩토링 노트)

논리적으로는 `App/scripts/` 가 더 적절하지만 **지금은 이동 금지**:

1. `watchdog_*` 등이 장기 실행 중 — 경로 변경 시 stale reference.
2. `sys.path` / `Path(__file__).parents[N]` 하드코딩 다수 — 일괄 수정 필요.
3. 외부 스케줄러/문서가 `scripts/xxx.py` 경로로 호출할 가능성.
4. Git blame 보존을 위해 `git mv` 로 원자 이동 필요.

**이동 계획** (백그라운드 작업 완전 종료 + Phase 3/4 완료 후):
- `git mv scripts/ App/scripts/`
- `sys.path.insert(0, ...)` 패치 (parent 인덱스 -1)
- 관련 README/문서 경로 갱신
- smoke_search / recalibrate / watchdog 재기동 회귀 테스트

---

## 참고

- **MR (Movie/Music)**: `MR_TriCHEF/scripts/` — `run_calibration.py`,
  `reindex_music_siglip2.py`, `post_batch_runner.py` 등.
- **DI (알고리즘 실험/벤치)**: `DI_TriCHEF/scripts/` — `bench_w5.py`,
  `build_img_caption_triple.py`, `run_doc_crossmodal_calib.py` 등.
- **⚠️ Deprecated 스크립트**: `MR_TriCHEF/scripts/fix_movie_segments.py` 는
  P2B.1 (replace_by_file) 이후 구조적으로 불필요. `FIX_MOVIE_SEGMENTS_FORCE=1`
  가드가 없으면 실행 거부됨.
