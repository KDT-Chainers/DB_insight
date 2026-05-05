"""services/trichef/lexical_rebuild.py — vocab/sparse/asf 재구축 공유 로직 (C-2 후반).

신규 파일이 incremental_runner 로 임베딩된 후, 이 모듈의 함수를 호출하여
lexical/ASF 채널에 누락되지 않도록 한다.

공유 정의:
  - image: 캡션만 사용 (원문 텍스트 없음)
  - doc_page: 캡션 + PDF 페이지 원문 합산 (cross-lingual KR/EN 커버)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import fitz
from scipy import sparse as sp
from tqdm import tqdm

from config import PATHS
from embedders.trichef import bgem3_sparse
from embedders.trichef.caption_io import load_caption, page_idx_from_stem
from embedders.trichef.doc_page_render import _sanitize, stem_key_for
from services.trichef import asf_filter, auto_vocab

logger = logging.getLogger(__name__)


# ── 도메인별 강제 포함 핵심 어휘 ─────────────────────────────────────────
# IDF 컷오프로 탈락되는 영어 핵심어를 vocab에 보장하기 위한 화이트리스트.
# 새 도메인 추가 시 여기에만 넣으면 된다.
_DOMAIN_FORCED_KEYWORDS: dict[str, list[str]] = {
    "movie": [
        # 장르/형식 (영어)
        "drama", "thriller", "horror", "comedy", "romance", "action", "documentary",
        "series", "episode", "scene", "season",
        # 우주/과학 영어 (NGC 코스모스, 보이저 등)
        "cosmos", "cosmo", "cosmic", "space", "universe", "planet", "galaxy", "star",
        "voyager", "probe", "spacecraft", "satellite", "NASA", "nasa", "orbit",
        "solar", "moon", "earth", "asteroid", "comet", "nebula",
        "golden", "record", "signal", "alien", "extraterrestrial",
        "astronomy", "milky", "spacetime", "sagan", "evolution", "biology",
        "relativity", "quantum", "electromagnetism",
        # 역사/문명 영어 (실크로드, 인류 시리즈)
        "silk", "road", "empire", "dynasty", "medieval", "civilization",
        "expedition", "conquest", "revolution", "invention", "pioneer",
        "history", "historical", "ancient", "culture", "heritage",
        # 과학/자연 영어 (과학을 보다, 기후 시리즈)
        "science", "scientific", "nature", "climate", "temperature", "global",
        "warming", "carbon", "environment", "environmental", "energy",
        "research", "experiment", "discovery", "theory",
        # 경제/사회 영어 (돈의 얼굴, 경제위기 시리즈)
        "economy", "economics", "economic", "finance", "financial",
        "money", "monetary", "currency", "investment", "inflation",
        "capitalism", "banking", "bank", "market", "trade", "budget",
        "interest", "rate", "crisis", "growth", "wealth",
        # 지식/강연 영어 (지식인초대석)
        "knowledge", "lecture", "expert", "professor", "scholar",
        # 제작/스태프
        "director", "actor", "actress", "producer", "film", "movie", "cinema",
        # 방송
        "news", "broadcast", "channel", "live", "interview", "report",
        # ── 한국어 시리즈 핵심어 (IDF 컷오프로 탈락 방지) ──────────────────
        # 우주/NGC 코스모스
        "코스모스", "보이저", "탐사선", "우주선", "골든디스크", "우주탐사",
        "은하수", "태양계", "블랙홀", "빅뱅", "초신성", "성운",
        "외계인", "외계생명체", "천문학", "천문학자",
        "우주", "탐사", "행성", "위성", "항성", "망원경",
        # 역사/실크로드
        "실크로드", "고선지", "당나라", "탈라스", "파미르", "둔황",
        "인류역사", "인류문명", "고대문명", "대제국",
        "역사", "문명", "고대", "중세", "제국",
        # 인류 다큐
        "흑사병", "산업혁명", "신대륙", "철기시대", "대항해",
        # 과학/자연 (과학을 보다, 기후 시리즈)
        "과학", "자연", "기후", "온난화", "탄소", "환경", "기온",
        "에너지", "연구", "실험", "발견", "이론", "생물",
        # 경제/사회 (돈의 얼굴, 한국경제 시리즈)
        "경제", "금융", "투자", "돈", "화폐", "인플레이션",
        "자본주의", "금리", "시장", "무역", "성장", "위기",
        "은행", "주식", "부", "자산", "물가", "예산",
        # 지식/강연 (지식인초대석)
        "지식", "강의", "강연", "학자", "교수", "전문가", "초대",
        "지식인", "학문", "이야기",
        # AI/기술 (김갑진, AI 강의 시리즈)
        "인공지능", "미래", "기술", "혁신", "디지털", "로봇",
    ],
    "music": [
        # 악기 (영어)
        "drum", "bass", "guitar", "piano", "violin", "flute", "saxophone",
        "trumpet", "cello", "harp", "organ", "keyboard",
        # 장르 (영어)
        "jazz", "rock", "pop", "hiphop", "rap", "classical", "electronic",
        "acoustic", "soul", "blues", "country", "folk", "reggae", "metal",
        "ballad", "ambient", "lofi", "indie", "kpop", "ost", "soundtrack",
        # 무드/분위기 (영어) — 이전에 누락된 핵심 항목
        "calm", "calming", "relaxing", "relaxed", "peaceful", "soothing",
        "upbeat", "energetic", "lively", "exciting", "vibrant",
        "romantic", "emotional", "sentimental", "atmospheric",
        "sad", "melancholic", "dark", "gloomy",
        "cheerful", "happy", "joyful",
        "intense", "powerful", "driving",
        "slow", "gentle", "soft", "mellow",
        "dreamy", "ethereal", "mysterious",
        # 용도 (영어)
        "study", "focus", "sleep", "meditation", "concentration",
        "workout", "background", "cinematic", "instrumental",
        # 음악 요소 (영어)
        "rhythm", "beat", "melody", "harmony", "tempo", "chord", "note",
        "lyric", "lyrics", "vocal", "chorus", "verse", "bridge",
        # 제작 (영어)
        "album", "track", "single", "mix", "remix", "live", "concert",
        # ── 한국어 음악 핵심어 ──────────────────────────────────────────
        # AI 뉴스/팟캐스트 (Rec 도메인 특성)
        "인공지능", "클로드", "ChatGPT", "LLM", "박태웅", "개발자",
        # 악기 (한국어)
        "피아노", "기타", "드럼", "바이올린", "첼로", "플루트", "트럼펫",
        "오케스트라", "현악기", "관악기", "타악기",
        # 장르 (한국어)
        "재즈", "록", "팝", "힙합", "랩", "클래식", "발라드",
        "인디", "가요", "팝송", "OST", "밴드", "솔로",
        # 무드/분위기 (한국어) — 핵심 누락 항목
        "잔잔한", "신나는", "편안한", "로맨틱",
        "감성", "감성적인", "조용한", "빠른", "느린",
        "슬픈", "우울한", "어두운", "행복한", "경쾌한", "활기찬",
        "몽환적", "몽환적인", "신비로운", "강렬한", "서정적",
        "포근한", "따뜻한", "차분한", "설레는", "웅장한",
        # 용도 (한국어)
        "공부", "집중", "수면", "명상", "배경음악", "분위기",
        "운동", "작업", "드라이브", "카페", "힐링",
        # 기본 음악 요소
        "멜로디", "리듬", "화음", "반주", "가사", "노래", "음악",
        "보컬", "악기", "연주", "합창",
    ],
    "image": [
        # 시각 기본 (영어)
        "image", "photo", "picture", "scene", "visual", "background",
        "portrait", "landscape", "color", "light", "shadow",
        # 피사체 (영어)
        "person", "people", "face", "hand", "animal", "object", "building",
        "nature", "sky", "water", "tree", "flower",
        # 구도/품질 (영어)
        "close", "wide", "zoom", "blur", "sharp", "bright", "dark",
        # 계절 (영어)
        "spring", "summer", "autumn", "fall", "winter",
        # 감정/표정 (영어)
        "smile", "smiling", "happy", "sad", "crying", "laughing",
        "portrait", "emotion", "expression",
        # 자연과학/생태 (영어)
        "wildlife", "ecology", "ecosystem", "habitat", "sparkling", "shining",
        # ── 한국어 시각 핵심어 (캡션 기반) ──────────────────────────────────
        # 인물/감정
        "사람", "여성", "남성", "어린이", "아이", "아기", "가족", "인물",
        "미소", "눈물", "행복", "슬픔",
        # 동물/반려동물
        "고양이", "강아지", "새", "토끼", "동물", "야생동물",
        # 식물/자연
        "꽃", "나무", "숲", "풀", "잔디",
        # 자연/경치/계절
        "자연", "풍경", "경치", "산", "바다", "강", "하늘", "구름", "호수",
        "노을", "석양", "일몰", "일출", "눈", "비",
        "봄", "여름", "가을", "겨울",
        # 도시/건물
        "건물", "도시", "거리", "공원", "다리",
        # 실내/실외
        "실내", "실외", "주방", "거실", "침실",
        # 사물
        "음식", "요리", "자동차", "자전거", "책",
        # 색상/시각 특성
        "빨간", "파란", "노란", "초록", "하얀", "검은",
        "빛나는", "반짝이는",
    ],
    "doc": [
        # 문서 구조 (영어)
        "document", "page", "chapter", "section", "figure", "table",
        "reference", "report", "analysis", "result", "conclusion",
        "data", "graph", "chart", "summary", "abstract",
        "article", "paper", "study", "research", "review",
        # 경제/재정 (영어) — 재정건전화법안 등 문서 특화
        "fiscal", "fiscal rule", "soundness", "consolidation",
        "legislation", "bill", "act", "statutory", "budget",
        "public finance", "government finance",
        # 환경/무역 (영어) — CBAM·탄소국경조정 문서 특화
        "CBAM", "carbon border", "carbon emission", "carbon tax",
        "EU CBAM", "greenhouse", "net zero", "carbon neutral",
        # ── 한국어 도메인 핵심 어근 ──────────────────────────────────────────
        # 경제/금융 — 복합어 strip 매칭으로 '경제지표를'→'경제' 등 포착
        "경제", "금융", "주식", "투자", "무역", "수출", "수입",
        "물가", "금리", "환율", "성장", "산업", "기업", "예산", "세금",
        "재정", "재정준칙", "건전화", "재정건전화", "법안", "입법",
        # AI/기술
        "인공지능", "기술", "반도체", "소프트웨어", "데이터", "플랫폼",
        "디지털", "정보", "보안", "자동화", "클라우드",
        # 정치/사회/법
        "정치", "정부", "선거", "사회", "문화", "역사", "교육",
        "정책", "법률", "규정", "국가", "지역", "의원", "행정",
        # 과학/의료
        "과학", "의료", "건강", "연구", "실험", "의학", "환경",
        # 통계/분석
        "통계", "분석", "지수", "현황", "조사", "결과", "평가", "보고서",
        # 사회/환경
        "기후", "에너지", "탄소", "지속", "환경", "재생",
        # 기업/경영
        "경영", "생산", "서비스", "개발", "관리", "운영", "계획",
    ],
}

_FORCED_KW_IDF = 3.5  # 강제 삽입 어휘의 기본 IDF (중간값)


def _inject_domain_keywords(vocab: dict, domain: str) -> dict:
    """vocab 빌드 후 IDF 컷오프로 탈락된 도메인 핵심어를 강제 삽입한다."""
    keywords = _DOMAIN_FORCED_KEYWORDS.get(domain, [])
    added = 0
    for kw in keywords:
        kl = kw.lower()
        if kl not in vocab:
            vocab[kl] = {"df": 0, "idf": _FORCED_KW_IDF}
            added += 1
    if added:
        logger.info(f"[lexical_rebuild:{domain}] forced-keyword inject: +{added}개")
    return vocab


# ── 공용 유틸 ───────────────────────────────────────────────────────────
def _encode_sparse(texts: list[str], batch: int = 64, max_length: int | None = None):
    """GPU(RTX 4070) FP16 BGE-M3 기준 batch=64 이 VRAM 내 최적 처리량."""
    parts = []
    for i in tqdm(range(0, len(texts), batch), desc="BGE-M3 Sparse"):
        chunk = texts[i:i + batch]
        kw = {"batch_size": batch}
        if max_length is not None:
            kw["max_length"] = max_length
        parts.append(bgem3_sparse.embed_passage_sparse(chunk, **kw))
    return sp.vstack(parts).tocsr()


def resolve_doc_pdf_map() -> dict[str, Path]:
    """doc registry → {sanitized_stem: resolved_pdf_path} (converted_pdf 우선).

    하위 호환: 신포맷(hash suffix)뿐 아니라 구포맷(hash 없는 sanitized stem)·
    raw stem(공백·한글 그대로)도 키로 등록해 search 단의 stem_key 가 어떤
    포맷이어도 PDF 를 찾을 수 있게 한다.
    """
    from embedders.trichef.doc_ingest import converted_pdf_path
    from embedders.trichef.doc_page_render import _sanitize  # type: ignore
    _CONV_EXT = {".hwp", ".hwpx", ".docx", ".doc", ".pptx", ".ppt",
                 ".xlsx", ".xls", ".odt", ".odp", ".ods", ".rtf"}
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    reg_path = cache / "registry.json"
    if not reg_path.exists():
        return {}
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    out: dict[str, Path] = {}
    for key, meta in registry.items():
        if not isinstance(meta, dict) or "abs" not in meta:
            continue
        src = Path(meta["abs"])
        target = src
        if src.suffix.lower() in _CONV_EXT:
            conv = converted_pdf_path(src)
            if conv is not None:
                target = conv

        rel_stem  = Path(key).stem
        sanitized = _sanitize(rel_stem)
        new_stem  = stem_key_for(key)

        # 다중 키 등록 — 신포맷이 우선이지만 구포맷·raw stem 도 동일 PDF로 매핑.
        # 충돌 시 신포맷이 이긴다 (신포맷이 마지막에 덮어쓰지 않게 setdefault).
        for k in (rel_stem, sanitized, new_stem):
            if not k:
                continue
            out.setdefault(k, target)
    return out


def _doc_page_texts(ids: list[str]) -> list[str]:
    """doc_page_ids → 페이지별 (캡션 + PDF원문) 텍스트 리스트."""
    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    stem_to_pdf = resolve_doc_pdf_map()

    pdf_text: dict[str, dict[int, str]] = {}
    unique_stems = sorted({Path(i).parts[1] for i in ids
                           if Path(i).parts[0] == "page_images" and len(Path(i).parts) >= 3})
    for stem in tqdm(unique_stems, desc="PDF text"):
        pdf = stem_to_pdf.get(stem)
        if not pdf or not pdf.exists() or pdf.stat().st_size == 0:
            pdf_text[stem] = {}
            continue
        try:
            with fitz.open(pdf) as d:
                pdf_text[stem] = {i: (p.get_text("text") or "") for i, p in enumerate(d)}
        except Exception as e:
            logger.warning(f"[lexical_rebuild] PDF open 실패 {pdf.name}: {e}")
            pdf_text[stem] = {}

    texts: list[str] = []
    for i in ids:
        parts = Path(i).parts
        if len(parts) < 3 or parts[0] != "page_images":
            texts.append("")
            continue
        stem = parts[1]
        page_stem = Path(parts[2]).stem
        cap = load_caption(extract / "captions" / stem, page_stem)
        pdf_txt = pdf_text.get(stem, {}).get(page_idx_from_stem(page_stem), "")
        texts.append((cap + "\n" + pdf_txt).strip())
    return texts


# ── 도메인별 엔트리포인트 ─────────────────────────────────────────────
def rebuild_image_lexical() -> dict:
    """image 도메인 vocab + asf_token_sets + sparse 재빌드."""
    cache = Path(PATHS["TRICHEF_IMG_CACHE"])
    ids_path = cache / "img_ids.json"
    if not ids_path.exists():
        return {"skipped": True, "reason": "img_ids.json 없음"}
    ids = json.loads(ids_path.read_text(encoding="utf-8"))["ids"]
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    # stem_key_for(i) 우선, 없으면 plain stem fallback (Qwen recaption_all 은 plain stem 사용)
    docs = []
    empty = 0
    for i in ids:
        txt = load_caption(cap_dir, stem_key_for(i))
        if not txt:
            txt = load_caption(cap_dir, Path(i).stem)
        if not txt:
            empty += 1
        docs.append(txt)
    logger.info(f"[lexical_rebuild:image] 캡션 로드: 빈 {empty}/{len(docs)}")

    vocab = auto_vocab.build_vocab(docs, min_df=2, max_df_ratio=0.5, top_k=8000)
    vocab = _inject_domain_keywords(vocab, "image")
    auto_vocab.save_vocab(cache / "auto_vocab.json", vocab)

    sets = asf_filter.build_doc_token_sets(docs, vocab)
    asf_filter.save_token_sets(cache / "asf_token_sets.json", sets)

    mat = _encode_sparse(docs)
    sp.save_npz(cache / "cache_img_sparse.npz", mat)

    logger.info(f"[lexical_rebuild:image] vocab={len(vocab)} "
                f"asf_nonempty={sum(1 for s in sets if s)}/{len(sets)} "
                f"sparse={mat.shape} nnz={mat.nnz}")
    return {"vocab": len(vocab), "sparse": list(mat.shape), "nnz": int(mat.nnz)}


def rebuild_doc_lexical() -> dict:
    """doc_page 도메인 vocab + asf_token_sets + sparse (캡션+PDF원문) 재빌드."""
    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    ids_path = cache / "doc_page_ids.json"
    if not ids_path.exists():
        return {"skipped": True, "reason": "doc_page_ids.json 없음"}
    ids = json.loads(ids_path.read_text(encoding="utf-8"))["ids"]

    texts = _doc_page_texts(ids)

    vocab = auto_vocab.build_vocab(texts, min_df=2, max_df_ratio=0.4, top_k=25000)
    vocab = _inject_domain_keywords(vocab, "doc")
    auto_vocab.save_vocab(cache / "auto_vocab.json", vocab)

    sets = asf_filter.build_doc_token_sets(texts, vocab)
    asf_filter.save_token_sets(cache / "asf_token_sets.json", sets)

    mat = _encode_sparse(texts, max_length=2048)
    sp.save_npz(cache / "cache_doc_page_sparse.npz", mat)

    logger.info(f"[lexical_rebuild:doc_page] vocab={len(vocab)} "
                f"asf_nonempty={sum(1 for s in sets if s)}/{len(sets)} "
                f"sparse={mat.shape} nnz={mat.nnz}")
    return {"vocab": len(vocab), "sparse": list(mat.shape), "nnz": int(mat.nnz)}


def _clean_filename(fname: str) -> str:
    """파일명에서 확장자, zip 아티팩트, 채널 태그 제거 → 제목 텍스트만 추출."""
    import re as _re
    # 확장자 제거 (.mp4 .mkv .mp3 등)
    fname = _re.sub(r'\.[a-zA-Z0-9]{2,4}$', '', fname)
    # .zip 아티팩트 제거 (예: "뉴스.zipMBC뉴스" → "뉴스 MBC뉴스")
    fname = fname.replace('.zip', ' ')
    # 대괄호 내용 제거 ([채널명])
    fname = _re.sub(r'\[.*?\]', '', fname)
    # 경로 구분자 이후 파일명만 (역슬래시/슬래시)
    fname = fname.split('/')[-1].split('\\')[-1]
    # 연속 공백 정리
    return _re.sub(r'\s+', ' ', fname).strip()


def _load_metadata_map(meta_path: Path) -> dict[str, str]:
    """metadata.json → {정규화된_stem: 풍부한_텍스트} 딕셔너리.

    key: 파일명 stem(확장자 제외, 소문자) 또는 원본 key
    value: title_ko + title_en + tags + synopsis 합산 텍스트
    """
    if not meta_path.exists():
        return {}
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[metadata] load 실패 {meta_path}: {e}")
        return {}
    result: dict[str, str] = {}
    for k, v in raw.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        parts: list[str] = []
        for field in ("title_ko", "title_en", "synopsis"):
            if v.get(field):
                parts.append(str(v[field]))
        for field in ("tags_ko", "tags_en"):
            if isinstance(v.get(field), list):
                parts.append(" ".join(v[field]))
        text = " ".join(parts)
        if not text:
            continue
        # 확장자 제거 후 소문자 키로 등록
        stem_key = Path(k).stem.lower()
        result[stem_key] = text
        result[k.lower()] = text   # 원본 키도 등록 (확장자 포함 경우 대비)
    return result


def _lookup_metadata(fname: str, meta_map: dict[str, str]) -> str:
    """파일명에서 metadata_map을 조회.
    exact → stem → prefix → keyword-in-stem 순으로 시도.

    4단계 fallback:
      1) exact stem match      (NGCcosmos e01... → key 정확히 일치)
      2) full fname lowercase  (확장자 포함 키 대비)
      3) prefix match          (stem이 key로 시작 or key가 stem[:30]으로 시작)
      4) keyword-in-stem       (key를 공백 제거 후 stem에 포함 여부 검사)
                               → 'donui eolgul' 같은 토픽 키가
                                  긴 YouTube 제목 안에 포함된 경우 매칭
    """
    if not fname or not meta_map:
        return ""
    stem = Path(fname).stem.lower()
    # 1) exact stem match
    if stem in meta_map:
        return meta_map[stem]
    # 2) full fname lowercase match (확장자 포함 키 대비)
    if fname.lower() in meta_map:
        return meta_map[fname.lower()]
    # 3) prefix match: metadata key가 stem의 앞부분인 경우
    for key, text in meta_map.items():
        if stem.startswith(key) or key.startswith(stem[:30]):
            return text
    # 4) keyword-in-stem match (공백 정규화 후 substring 검사)
    #    최소 3자(한글 인명/단어 포함) 이상의 키만 사용해 오탐 방지
    stem_ns = stem.replace(" ", "").replace("​", "")
    for key, text in meta_map.items():
        kns = key.replace(" ", "")
        if len(kns) >= 3 and kns in stem_ns:
            return text
    return ""


def _av_stt_texts(segments: list[dict],
                  metadata_map: dict[str, str] | None = None) -> list[str]:
    """AV segments → (파일명 제목 + 메타데이터 + STT + 이중언어 확장) 결합 텍스트 리스트.

    file_name 에 포함된 영상 제목을 STT 앞에 붙여 lexical 커버리지 향상.
    metadata_map 이 제공되면 파일별 제목·줄거리·태그를 텍스트에 삽입해
    dense/sparse/ASF 모두 메타데이터 기반 검색 가능.
    expand_bilingual 을 적용해 한→영 / 영→한 토큰을 추가.
    STT 없으면 제목만, 둘 다 없으면 빈 문자열.
    """
    try:
        from services.query_expand import expand_bilingual as _eb
    except Exception:
        _eb = None

    # 루트 폴더 패턴 (카테고리가 아닌 수집자/배치 폴더)
    # 예: 태윤_2차, 태윤_3차, 훤_youtube_2차, YS_다큐_1차, 정혜_BGM_1차 등
    import re as _re_av
    _ROOT_FOLDER_PAT = _re_av.compile(
        r'^[가-힣a-zA-Z0-9]+_(?:[a-zA-Z가-힣0-9]+_)?\d+차?$', _re_av.IGNORECASE
    )

    result = []
    for s in segments:
        stt   = str(s.get("stt_text")  or "").strip()
        # file_name = 파일명만, file = 상대 경로 포함
        file_path = str(s.get("file") or "").strip()
        fname     = str(s.get("file_name") or file_path or "").strip()
        title = _clean_filename(fname) if fname else ""

        # 카테고리 서브폴더 이름 추출 (예: 태윤_2차/음악/love letter.wav → "음악")
        # 루트 폴더(태윤_2차 등)가 아닌 의미 있는 서브폴더만 주입
        category = ""
        if file_path:
            parts = Path(file_path).parts
            if len(parts) >= 3:
                # parts[-2] = 직계 부모 폴더 (파일명 제외)
                parent = parts[-2]
                if not _ROOT_FOLDER_PAT.match(parent):
                    category = parent
            elif len(parts) == 2:
                # e.g., YS_1차/song.m4a — 루트가 직계 부모
                parent = parts[0]
                if not _ROOT_FOLDER_PAT.match(parent):
                    category = parent
        if category:
            title = f"{category} {title}".strip()

        # 숫자 전용 파일명(001.mp4 등): 루트 폴더에서 의미 있는 토큰 추출
        # 예: 정혜_BGM_1차/001.mp4 → category="BGM 정혜" 주입
        if not category and fname and Path(fname).stem.isdigit() and file_path:
            fp_parts = Path(file_path).parts
            root_folder = (fp_parts[-2] if len(fp_parts) >= 2
                           else (fp_parts[0] if fp_parts else ""))
            if root_folder:
                tokens = _re_av.findall(r'[A-Z]{2,}|[가-힣]{2,}', root_folder)
                if tokens:
                    title = f"{' '.join(tokens)} {title}".strip()

        # 파일별 메타데이터 조회 (있는 경우에만 삽입)
        meta  = _lookup_metadata(fname, metadata_map) if metadata_map else ""
        if meta:
            base = f"{title} {meta} {stt}".strip()
        else:
            base = f"{title} {stt}".strip() if (title and stt) else (title or stt)
        if _eb and base:
            try:
                base = _eb(base, max_extra=12)
            except Exception:
                pass
        result.append(base)
    return result


def rebuild_movie_lexical() -> dict:
    """movie 도메인 vocab + {prefix}_token_sets + sparse (STT 원문) 재빌드.

    Engine._build_av_entry 가 cache_movie_sparse.npz 를 자동 로드하므로
    이 함수 실행 후 Engine 재기동 또는 _load_all() 재호출이 필요.
    movie_metadata.json 이 cache 에 있으면 메타데이터를 텍스트에 삽입해
    dense/sparse/ASF 채널 모두 메타 기반 검색이 가능해진다.
    """
    cache = Path(PATHS["TRICHEF_MOVIE_CACHE"])
    segs_path = cache / "segments.json"
    if not segs_path.exists():
        return {"skipped": True, "reason": "segments.json 없음"}
    segments = json.loads(segs_path.read_text(encoding="utf-8"))
    # 메타데이터 맵 로드 (title/synopsis/tags → dense+sparse+ASF 커버리지 향상)
    meta_map = _load_metadata_map(cache / "movie_metadata.json")
    logger.info(f"[movie] metadata entries={len(meta_map)//2}")  # 키 2개씩 등록
    texts = _av_stt_texts(segments, metadata_map=meta_map)
    if not any(texts):
        return {"skipped": True, "reason": "STT 텍스트 없음"}

    vocab = auto_vocab.build_vocab(texts, min_df=2, max_df_ratio=0.5, top_k=25000)
    vocab = _inject_domain_keywords(vocab, "movie")
    auto_vocab.save_vocab(cache / "vocab_movie.json", vocab)

    sets = asf_filter.build_doc_token_sets(texts, vocab)
    asf_filter.save_token_sets(cache / "movie_token_sets.json", sets)

    mat = _encode_sparse(texts, max_length=512)
    sp.save_npz(cache / "cache_movie_sparse.npz", mat)

    logger.info(f"[lexical_rebuild:movie] vocab={len(vocab)} "
                f"asf_nonempty={sum(1 for s in sets if s)}/{len(sets)} "
                f"sparse={mat.shape} nnz={mat.nnz}")
    return {"vocab": len(vocab), "sparse": list(mat.shape), "nnz": int(mat.nnz)}


def rebuild_music_lexical() -> dict:
    """music 도메인 vocab + {prefix}_token_sets + sparse (STT 원문) 재빌드."""
    cache = Path(PATHS["TRICHEF_MUSIC_CACHE"])
    segs_path = cache / "segments.json"
    if not segs_path.exists():
        return {"skipped": True, "reason": "segments.json 없음"}
    segments = json.loads(segs_path.read_text(encoding="utf-8"))
    texts = _av_stt_texts(segments)
    if not any(texts):
        return {"skipped": True, "reason": "STT 텍스트 없음"}

    vocab = auto_vocab.build_vocab(texts, min_df=2, max_df_ratio=0.5, top_k=15000)
    vocab = _inject_domain_keywords(vocab, "music")
    auto_vocab.save_vocab(cache / "vocab_music.json", vocab)

    sets = asf_filter.build_doc_token_sets(texts, vocab)
    asf_filter.save_token_sets(cache / "music_token_sets.json", sets)

    mat = _encode_sparse(texts, max_length=512)
    sp.save_npz(cache / "cache_music_sparse.npz", mat)

    logger.info(f"[lexical_rebuild:music] vocab={len(vocab)} "
                f"asf_nonempty={sum(1 for s in sets if s)}/{len(sets)} "
                f"sparse={mat.shape} nnz={mat.nnz}")
    return {"vocab": len(vocab), "sparse": list(mat.shape), "nnz": int(mat.nnz)}
