"""services/bgm — 5번째 도메인 (Background Music) 검색 패키지.

TriCHEF(MR_TriCHEF/DI_TriCHEF)와 분리된 독립 파이프라인:
  - 로컬 우선: Chromaprint(exact) + CLAP(semantic) + librosa(rule-based tags)
  - 외부 API: ACRCloud (settings.json `bgm.api_enabled` 스위치 OFF 시 호출 0건)
  - 인덱스 위치: Data/embedded_DB/Bgm/

진입점:
  - services.bgm.search_engine.search(query, ...)
  - services.bgm.search_engine.identify(audio_path, ...)
  - services.bgm.ingest_pipeline.build_index(...)
"""
