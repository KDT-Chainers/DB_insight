"""한↔영 쿼리 확장 — 의미 동일 다국어 토큰을 검색 쿼리에 추가.

배경:
  BGE-M3 dense 임베딩은 다국어 의미를 잘 포착하지만, sparse 채널과
  ASF token 매칭은 정확한 토큰 일치만 가능 → '어린이' 와 'children' 검색
  결과가 달라짐.

해결:
  검색 시점에 query 를 자동 확장:
    '어린이' → '어린이 children kids child'
    'children' → 'children 어린이 아이들'
  이렇게 하면 sparse + ASF 도 다국어 토큰 모두 커버.

사용:
  from services.query_expand import expand_bilingual
  expanded = expand_bilingual('어린이')  # '어린이 children kids child'
"""
from __future__ import annotations
import re

# 한↔영 양방향 사전 — 자주 쓰이는 도메인 어휘 + 일반 명사
_KO_EN: dict[str, list[str]] = {
    # 인물 / 사람
    "어린이":   ["children", "kids", "child"],
    "아이들":   ["children", "kids"],
    "아이":     ["child", "kid"],
    "사람":     ["person", "people"],
    "인물":     ["person", "portrait"],
    "여성":     ["woman", "female"],
    "남성":     ["man", "male"],
    "학생":     ["student"],
    "선생":     ["teacher"],
    "교사":     ["teacher"],
    "노인":     ["elderly", "senior"],
    "가족":     ["family"],

    # 장소 / 자연
    "바다":     ["sea", "ocean", "beach"],
    "산":       ["mountain"],
    "산맥":     ["mountain", "mountains"],
    "강":       ["river"],
    "도시":     ["city", "urban"],
    "건물":     ["building", "structure"],
    "공원":     ["park"],
    "학교":     ["school"],
    "회사":     ["company", "office"],
    "사무실":   ["office"],
    "도서관":   ["library"],
    "박물관":   ["museum"],

    # 동물 / 자연물
    "고양이":   ["cat", "kitten"],
    "강아지":   ["dog", "puppy"],
    "개":       ["dog"],
    "새":       ["bird"],
    "물고기":   ["fish"],
    "꽃":       ["flower", "flowers"],
    "나무":     ["tree", "trees"],
    "풀":       ["grass"],

    # 사물
    "노트북":   ["laptop", "notebook"],
    "컴퓨터":   ["computer", "PC"],
    "자동차":   ["car", "vehicle", "automobile"],
    "운전":     ["driving", "drive"],
    "음식":     ["food", "meal"],
    "옷":       ["clothes", "clothing"],
    "책":       ["book"],
    "문서":     ["document", "paper"],
    "사진":     ["photo", "photograph", "picture"],
    "그림":     ["drawing", "picture", "image"],

    # 활동 / 상태
    "회의":     ["meeting", "conference"],
    "발표":     ["presentation", "report"],
    "강의":     ["lecture", "lesson"],
    "분석":     ["analysis", "analytical"],
    "연구":     ["research", "study"],
    "교육":     ["education", "educational"],
    "취업":     ["employment", "employ", "job", "career"],
    "투자":     ["investment", "invest"],
    "운영":     ["operation"],
    "관리":     ["management", "manage"],
    "개발":     ["development", "develop"],
    "지원":     ["support"],
    "보고서":   ["report"],
    "통계":     ["statistics", "statistical"],
    "정책":     ["policy", "policies"],
    "예산":     ["budget", "fiscal"],
    "건강":     ["health"],
    "보험":     ["insurance"],
    "산업":     ["industry", "industrial"],
    "기업":     ["company", "enterprise"],
    "시장":     ["market"],

    # 기술 / IT
    "기술":     ["technology", "technical"],
    "정보":     ["information"],
    "데이터":   ["data"],
    "데이터센터": ["data center", "datacenter"],
    "인공지능": ["ai", "artificial intelligence"],
    "보안":     ["security"],
    "서비스":   ["service"],

    # 분위기 / 형용사
    "밝은":     ["bright"],
    "어두운":   ["dark"],
    "잔잔한":   ["calm", "quiet", "peaceful"],
    "신나는":   ["upbeat", "energetic"],
    "조용한":   ["quiet", "silent"],

    # 음악 (BGM 도메인)
    "음악":     ["music"],
    "노래":     ["song"],
    "피아노":   ["piano"],
    "기타":     ["guitar"],
    "드럼":     ["drum", "drums"],
    "오케스트라": ["orchestra"],
    "발라드":   ["ballad"],
    "댄스":     ["dance"],
    "록":       ["rock"],
    "재즈":     ["jazz"],
}

# 영 → 한 역방향 lookup (자동 생성)
_EN_KO: dict[str, list[str]] = {}
for _ko, _ens in _KO_EN.items():
    for _en in _ens:
        _EN_KO.setdefault(_en.lower(), []).append(_ko)


def expand_bilingual(query: str, max_extra: int = 8) -> str:
    """쿼리를 한↔영 양방향 사전으로 확장.

    예:
      '어린이' → '어린이 children kids child'
      'cat' → 'cat 고양이'
      '취업 통계' → '취업 통계 employment statistics employ statistical'
      '산 풍경' (사전 미등록) → '산 풍경 mountain' (산만 매핑)

    Args:
      query: 원본 쿼리
      max_extra: 추가할 토큰 최대 수 (너무 많으면 sparse 노이즈)
    """
    if not query or not query.strip():
        return query

    # 토큰 추출 — 한글/영문/숫자
    tokens = re.findall(r"[가-힣]+|[A-Za-z]+|[0-9]+", query)
    if not tokens:
        return query

    extras: list[str] = []
    seen: set[str] = {t.lower() for t in tokens}

    for t in tokens:
        # 한 → 영
        for en in _KO_EN.get(t, []):
            el = en.lower()
            if el not in seen:
                extras.append(en)
                seen.add(el)
                if len(extras) >= max_extra:
                    break
        if len(extras) >= max_extra:
            break
        # 영 → 한
        for ko in _EN_KO.get(t.lower(), []):
            if ko not in seen:
                extras.append(ko)
                seen.add(ko)
                if len(extras) >= max_extra:
                    break
        if len(extras) >= max_extra:
            break

    if not extras:
        return query
    return f"{query} {' '.join(extras)}"
