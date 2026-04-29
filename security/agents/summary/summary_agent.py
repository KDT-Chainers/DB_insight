"""
agents/summary/summary_agent.py
──────────────────────────────────────────────────────────────────────────────
Summary Agent — 검색 결과를 읽기 쉽게 정리하는 생성 담당 에이전트.
"""
from __future__ import annotations

import logging
import re
import textwrap
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import config
from harness.safe_llm_call import safe_llm_call

logger = logging.getLogger(__name__)


@dataclass
class SummaryResult:
    text: str
    used_llm: bool = False
    regenerated: bool = False
    map_reduce_used: bool = False
    source_chunk_count: int = 0
    error: Optional[str] = None

    def is_ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


class SummaryAgent:
    _PROMPT_CONSTRAINTS = textwrap.dedent("""\
        [요약 규칙 - 반드시 준수]
        1. 참고 문서의 내용을 바탕으로 사용자 요청에 맞는 답변을 작성하라.
        2. 줄거리·스토리 요청이면 등장인물, 사건 흐름, 결말을 포함해 서술하라.
        3. 아래 개인정보는 절대 원문/부분값 그대로 출력하지 말 것:
           - 주민등록번호, 계좌번호, 여권번호, 운전면허번호, 사업자등록번호, 카드번호
        4. 개인정보는 반드시 일반화된 표현으로 축약할 것
           (예: "[개인정보 포함]", "[민감정보 생략]").
        5. 원문을 그대로 복사/붙여넣기 하지 말고 핵심만 재구성하라.
        6. 반드시 한국어(Korean)로만 작성하라. 영어·중국어·일본어 등 다른 언어는 절대 사용 금지.
           참고 문서가 외국어로 되어 있어도 출력은 반드시 한국어로 번역하여 작성하라.
        7. 최대 3~5줄 이내로 간결하게 작성하라.
    """)

    def __init__(self) -> None:
        self._ollama_url = config.OLLAMA_URL
        self._model = getattr(config, "SUMMARY_MODEL", "qwen2.5:3b")
        self._timeout = getattr(config, "SUMMARY_TIMEOUT_SEC", 60)
        self._max_chars = getattr(config, "SUMMARY_MAX_CHARS", 1200)
        self._max_chunks = getattr(config, "SUMMARY_MAX_CHUNKS", 5)
        # USE_QWEN(분류용)과 독립. SUMMARY_USE_LLM=1이면 Ollama로 진짜 요약.
        self._use_llm = bool(getattr(config, "SUMMARY_USE_LLM", True))

    def _ollama_available(self) -> bool:
        """Ollama 서버 응답 여부 빠르게 확인 (2초 타임아웃)."""
        import urllib.request, urllib.error
        try:
            url = self._ollama_url.rstrip("/") + "/api/tags"
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            return False

    def summarize(self, user_query: str, chunks: List[Dict[str, Any]]) -> SummaryResult:
        if not chunks:
            return SummaryResult(text="요약할 내용이 없습니다. 관련 문서를 먼저 업로드해주세요.")
        chunks = self._order_chunks(chunks)

        threshold = getattr(config, "MAP_REDUCE_THRESHOLD", 6)
        if self._use_llm and len(chunks) >= threshold:
            if self._ollama_available():
                logger.info(
                    "[SummaryAgent] 청크 %d개 ≥ %d → map-reduce 요약", len(chunks), threshold
                )
                return self._summarize_map_reduce(user_query, chunks)
            logger.warning("[SummaryAgent] Ollama 미응답(map-reduce) → extractive fallback")
            context = self._extract_context(chunks[: self._max_chunks])
            return self._run_fallback(context, len(chunks))

        selected = chunks[: self._max_chunks]
        context = self._extract_context(selected)
        count = len(selected)
        if self._use_llm and self._ollama_available():
            return self._run_llm(user_query, context, count)
        if self._use_llm:
            logger.warning("[SummaryAgent] Ollama 미응답 → extractive fallback")
        return self._run_fallback(context, count)

    def summarize_with_constraints(
        self,
        user_query: str,
        chunks: List[Dict[str, Any]],
        constraints: Optional[str] = None,
    ) -> SummaryResult:
        if not chunks:
            return SummaryResult(text="재생성할 내용이 없습니다.", regenerated=True)
        chunks = self._order_chunks(chunks)
        selected = chunks[: self._max_chunks]
        context = self._extract_context(selected)
        count = len(selected)
        extra_constraint = f"\n[추가 제약] {constraints}" if constraints else ""
        if self._use_llm:
            return self._run_llm(user_query, context, count, regenerated=True, extra_constraint=extra_constraint)
        return self._run_fallback(context, count, regenerated=True)

    @staticmethod
    def _looks_like_toc(text: str) -> bool:
        """목차·제목 행처럼 실질 내용이 없는 청크 여부 판별."""
        stripped = text.strip()
        lines = [l.strip() for l in stripped.splitlines() if l.strip()]
        if len(lines) == 0:
            return True
        # 전체 줄이 5줄 이하이고 평균 길이 30자 미만 → 목차/헤더 추정
        avg_len = sum(len(l) for l in lines) / len(lines)
        if len(lines) <= 5 and avg_len < 30:
            return True
        # 줄의 50% 이상이 숫자·점·공백으로만 이루어진 경우 (페이지 번호열)
        dot_lines = sum(1 for l in lines if re.match(r'^[\d\s\.\-·…·]+$', l))
        if dot_lines / len(lines) > 0.5:
            return True
        return False

    @staticmethod
    def _order_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """줄거리 요약 품질 향상을 위해 페이지/오프셋 기준으로 정렬."""
        return sorted(
            chunks,
            key=lambda c: (
                int(c.get("source_page") or 0),
                int(c.get("chunk_index") or 0),
                int(c.get("start_char") or 0),
            ),
        )

    def _extract_context(self, chunks: List[Dict[str, Any]]) -> str:
        seen_prefixes: set[str] = set()
        parts = []
        skipped_toc = 0
        for i, c in enumerate(chunks, 1):
            text = c.get("text", "").strip()
            fname = c.get("file_name") or c.get("doc_name") or ""
            if not text:
                if c.get("is_image"):
                    parts.append(f"[문서 {i}] {fname}: [이미지 파일]")
                continue
            # 목차·헤더처럼 보이는 청크는 제외
            if self._looks_like_toc(text):
                skipped_toc += 1
                continue
            # 앞 60자가 같은 중복 청크 제외
            prefix = text[:60].strip()
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            header = f"[문서 {i}] {fname}:" if fname else f"[문서 {i}]:"
            parts.append(f"{header}\n{text}")
        if skipped_toc and not parts:
            # 전부 목차로 판정됐을 때 — 그냥 다 넣기
            logger.warning("[SummaryAgent] 모든 청크가 목차 추정 → 필터 해제")
            for i, c in enumerate(chunks, 1):
                text = c.get("text", "").strip()
                fname = c.get("file_name") or c.get("doc_name") or ""
                if text:
                    header = f"[문서 {i}] {fname}:" if fname else f"[문서 {i}]:"
                    parts.append(f"{header}\n{text}")
        combined = "\n\n".join(parts)
        if len(combined) > self._max_chars:
            combined = combined[: self._max_chars] + "\n...(이하 생략)"
        return combined

    def _build_prompt(self, user_query: str, context: str, extra_constraint: str = "") -> str:
        return (
            f"{self._PROMPT_CONSTRAINTS}"
            f"{extra_constraint}\n\n"
            f"[사용자 요청]\n{user_query}\n\n"
            f"[참고 문서]\n{context}\n\n"
            "[요약 결과]\n"
        )

    def _run_llm(
        self,
        user_query: str,
        context: str,
        source_count: int,
        regenerated: bool = False,
        extra_constraint: str = "",
    ) -> SummaryResult:
        started = time.monotonic()
        try:
            response = self._call_qwen(user_query, context, extra_constraint)
            elapsed = time.monotonic() - started
            logger.info("[SummaryAgent] LLM 요약 완료 (%.2fs, chunks=%d)", elapsed, source_count)
            return SummaryResult(
                text=self._format_output(response),
                used_llm=True,
                regenerated=regenerated,
                source_chunk_count=source_count,
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            logger.warning("[SummaryAgent] LLM 실패(%.2fs) → fallback 전환: %s", elapsed, exc)
            return self._run_fallback(context, source_count, regenerated)

    def _summarize_map_reduce(
        self, user_query: str, chunks: List[Dict[str, Any]]
    ) -> SummaryResult:
        """
        Map-Reduce 요약:
          Map  — chunks를 GROUP_SIZE 개씩 묶어 각 그룹을 개별 요약
          Reduce — 그룹 요약들을 하나의 최종 요약으로 통합
        """
        group_size = getattr(config, "MAP_REDUCE_GROUP_SIZE", 3)
        groups = [chunks[i : i + group_size] for i in range(0, len(chunks), group_size)]
        total_groups = len(groups)
        logger.info("[SummaryAgent] map-reduce: %d개 청크 → %d그룹", len(chunks), total_groups)

        mini_summaries: List[str] = []
        for idx, group in enumerate(groups, 1):
            context = self._extract_context(group)
            if not context.strip():
                continue
            extra = f"\n[참고: 이 내용은 전체 문서의 {idx}/{total_groups} 구간입니다]"
            try:
                mini = self._call_qwen(user_query, context, extra_constraint=extra)
                if mini.strip():
                    mini_summaries.append(mini.strip())
                    logger.debug("[SummaryAgent] map %d/%d 완료 (%d자)", idx, total_groups, len(mini))
            except Exception as exc:
                logger.warning("[SummaryAgent] map %d/%d 실패: %s", idx, total_groups, exc)

        if not mini_summaries:
            logger.warning("[SummaryAgent] map 단계 전부 실패 → extractive fallback")
            context = self._extract_context(chunks[: self._max_chunks])
            return self._run_fallback(context, len(chunks))

        # ── Reduce ──────────────────────────────────────────────────────────
        combined = "\n\n".join(
            f"[구간 {i + 1}]\n{s}" for i, s in enumerate(mini_summaries)
        )
        reduce_prompt = (
            "[최종 요약 규칙]\n"
            "아래는 동일 문서의 여러 구간에 대한 개별 요약이다.\n"
            "이를 하나의 자연스러운 전체 요약으로 통합하라.\n"
            "줄거리·스토리 요청이면 사건 순서와 흐름이 드러나도록 서술하라.\n"
            "주민번호/계좌/여권/운전면허/사업자등록/카드번호는 절대 직접 출력하지 말고 "
            "'[개인정보 포함]'으로만 표시하라.\n"
            "원문 문장을 그대로 복사하지 말고 핵심만 재구성하라.\n"
            "반드시 한국어(Korean)로만 작성하라. 영어·중국어·일본어 등 다른 언어는 절대 사용 금지.\n"
            "최대 3~5줄로 작성하라.\n\n"
            f"[사용자 요청]\n{user_query}\n\n"
            f"[구간별 요약]\n{combined}\n\n"
            "[최종 요약 (한국어)]\n"
        )
        try:
            final = safe_llm_call(
                lambda: self._call_qwen_raw(reduce_prompt),
                timeout_sec=float(self._timeout),
                max_retries=1,
                call_name="summary_reduce_call",
            )
        except Exception as exc:
            logger.warning("[SummaryAgent] reduce 실패 → 구간 요약 이어붙임: %s", exc)
            final = "\n\n".join(mini_summaries)

        logger.info(
            "[SummaryAgent] map-reduce 완료: %d그룹 → 최종 %d자", total_groups, len(final)
        )
        return SummaryResult(
            text=self._format_output(final),
            used_llm=True,
            map_reduce_used=True,
            source_chunk_count=len(chunks),
        )

    def _call_qwen_raw(self, prompt: str) -> str:
        """완성된 프롬프트를 Ollama에 직접 전송한다 (reduce 단계용)."""
        import httpx

        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 768,
            },
        }
        resp = httpx.post(
            f"{self._ollama_url}/api/generate",
            json=payload,
            timeout=httpx.Timeout(self._timeout, connect=min(3.0, float(self._timeout))),
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()

    def _call_qwen(self, user_query: str, context: str, extra_constraint: str = "") -> str:
        return safe_llm_call(
            lambda: self._call_qwen_raw(
                self._build_prompt(user_query, context, extra_constraint)
            ),
            timeout_sec=float(self._timeout),
            max_retries=1,
            call_name="summary_map_call",
        )

    def _run_fallback(self, context: str, source_count: int, regenerated: bool = False) -> SummaryResult:
        lines = self._extractive_fallback(context)
        return SummaryResult(
            text=self._format_output("\n".join(lines)),
            used_llm=False,
            regenerated=regenerated,
            source_chunk_count=source_count,
        )

    def _extractive_fallback(self, context: str) -> List[str]:
        blocks = re.split(r"\[문서 \d+\]", context)
        results: List[str] = []
        seen: set[str] = set()
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            for line in lines:
                if line.endswith(":") and len(line) < 60:
                    continue
                if len(line) < 10:
                    continue
                snippet = line[:120].strip()
                if snippet in seen:
                    continue
                seen.add(snippet)
                results.append(snippet)
                break
            if len(results) >= 5:
                break
        if not results:
            return ["관련 내용을 찾았으나 요약 가능한 텍스트가 부족합니다."]
        return results

    # ── 언어 필터 ──────────────────────────────────────────────────────────────

    _KO_RE = re.compile(r'[\uAC00-\uD7A3]')                            # 완성형 한글 음절
    _CN_RE = re.compile(r'[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF]')  # CJK 한자

    @classmethod
    def _filter_non_korean_lines(cls, text: str) -> str:
        """
        LLM 출력 줄 중 '완전히 외국어인 줄'만 제거한다.

        제거 조건 (모두 충족해야 제거):
          - 완성형 한글 음절(가-힣)이 하나도 없음
          - 한자가 3자 이상 포함

        한글이 한 글자라도 있으면 유지 (외국어 고유명사 혼재 허용).
        """
        lines = text.splitlines()
        kept = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                kept.append(line)
                continue
            ko = len(cls._KO_RE.findall(stripped))
            cn = len(cls._CN_RE.findall(stripped))
            if ko == 0 and cn >= 3:
                logger.debug("[SummaryAgent] 외국어 전용 줄 제거: %r", stripped[:60])
                continue
            kept.append(line)
        return "\n".join(kept).strip()

    def _format_output(self, raw: str) -> str:
        if not raw or not raw.strip():
            return "요약 결과가 없습니다."
        # 완전한 외국어 줄만 제거 (한글이 한 자라도 있으면 유지)
        filtered = self._filter_non_korean_lines(raw)
        # 필터 후 텍스트가 사라지면 원문 그대로 사용 (과도한 필터링 방지)
        if not filtered.strip():
            logger.warning("[SummaryAgent] 언어 필터 후 내용 없음 → 원문 유지")
            filtered = raw
        lines = [l.strip() for l in filtered.strip().splitlines() if l.strip()]
        out = []
        for line in lines:
            out.append(line if line.startswith(("-", "•", "*")) else f"- {line}")
        # 프롬프트 제약(3~5줄)을 출력 포맷 단계에서도 한 번 더 강제
        if len(out) > 5:
            out = out[:5]
        return "\n".join(out)

