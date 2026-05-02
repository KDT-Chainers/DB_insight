"""faster-whisper STT 래퍼 (GPU int8_float16).

[항목5] LoRA adapter_path 지원:
  WHISPER_ADAPTER_PATH 가 설정되면 faster-whisper의 local 모델로 로드.
  빈 문자열이면 기본 MODEL_WHISPER (large-v3) 사용.

[항목6] batch_transcribe() 추가:
  여러 파일을 순차 STT 후 결과 dict 목록 반환.
  단 한 번만 모델 로드 → 호출마다 로드하는 것 대비 VRAM 효율 개선.

[GPU 가속] faster-whisper 1.1+ 의 BatchedInferencePipeline 으로 단일 파일 내
  세그먼트 병렬 처리 → RTX 4070 Laptop 에서 2~4x 추가 가속.
  환경변수 OMC_DISABLE_WHISPER_BATCH=1 로 강제 OFF.
"""
from __future__ import annotations

import gc
import logging
import os
from pathlib import Path

import torch

from .paths import MODEL_WHISPER, WHISPER_ADAPTER_PATH

logger = logging.getLogger(__name__)


def _batch_enabled() -> bool:
    return os.environ.get("OMC_DISABLE_WHISPER_BATCH", "").strip().lower() not in ("1", "true", "yes")


class WhisperSTT:
    def __init__(self, model_size: str = MODEL_WHISPER,
                 device: str = "cuda", compute_type: str = "float16",
                 adapter_path: str = WHISPER_ADAPTER_PATH):
        # NOTE: CUDA + int8 on faster-whisper triggers STATUS_STACK_BUFFER_OVERRUN
        # on unload (Windows). CUDA + float16 은 안정적이며 CPU int8 대비 5~10x 빠름.
        # 1~2시간 long-form audio batch 처리에 권장.
        from faster_whisper import WhisperModel
        # [항목5] adapter_path 우선 사용 (로컬 파인튜닝 체크포인트)
        model_id = adapter_path if adapter_path else model_size
        self.model = WhisperModel(model_id, device=device,
                                  compute_type=compute_type)
        # Lazy 생성: 첫 transcribe 호출 시 BatchedInferencePipeline 빌드.
        self._batched = None
        self._batched_failed = False  # 한번 실패하면 재시도하지 않음

    def _get_batched(self):
        if self._batched is not None or self._batched_failed:
            return self._batched
        if not _batch_enabled():
            self._batched_failed = True
            return None
        try:
            from faster_whisper import BatchedInferencePipeline
            self._batched = BatchedInferencePipeline(model=self.model)
            logger.info("[whisper] BatchedInferencePipeline 활성화 (2~4x 가속)")
        except Exception as e:
            logger.warning(f"[whisper] BatchedInferencePipeline 미지원, 순차 모드: {e}")
            self._batched_failed = True
        return self._batched

    def transcribe(self, wav_path: Path, language: str | None = None) -> list[dict]:
        """단일 파일 STT → [{start, end, text}, ...].

        다층 OOM 폴백:
          1. batched (batch_size=8) — 가장 빠름
          2. batched (batch_size=2) — OOM 시 축소 재시도
          3. 순차 transcribe — 최후 안전망
        """
        # 1차: BatchedInferencePipeline batch=8 (GPU 병렬)
        batched = self._get_batched()
        if batched is not None:
            for bs in (8, 2):
                try:
                    segments, _info = batched.transcribe(
                        str(wav_path),
                        language=language,
                        vad_filter=True,
                        batch_size=bs,
                    )
                    out = [{
                        "start": round(float(s.start), 3),
                        "end":   round(float(s.end),   3),
                        "text":  (s.text or "").strip(),
                    } for s in segments]
                    if bs != 8:
                        logger.info(f"[whisper] batch_size={bs} 으로 처리 성공 (OOM 회복)")
                    return out
                except torch.cuda.OutOfMemoryError as oom:
                    logger.warning(f"[whisper] batched bs={bs} OOM, "
                                   f"empty_cache 후 축소 재시도: {oom}")
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    # bs=2 도 실패하면 다음 단계(순차)로
                    if bs == 2:
                        self._batched = None
                        self._batched_failed = True
                except Exception as e:
                    logger.warning(f"[whisper] batched 실패, 순차 폴백: {e}")
                    self._batched = None
                    self._batched_failed = True
                    break

        # 2차 (폴백): 기존 순차 transcribe — OOM 시 한 번 더 cache 정리 후 재시도
        for attempt in range(2):
            try:
                segments, _info = self.model.transcribe(
                    str(wav_path),
                    language=language,          # None = auto-detect
                    vad_filter=True,
                    beam_size=1,
                    condition_on_previous_text=False,
                )
                out: list[dict] = []
                for s in segments:
                    out.append({
                        "start": round(float(s.start), 3),
                        "end":   round(float(s.end),   3),
                        "text":  (s.text or "").strip(),
                    })
                return out
            except torch.cuda.OutOfMemoryError as oom:
                logger.warning(f"[whisper] 순차 OOM (attempt {attempt+1}), empty_cache 후 재시도: {oom}")
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                if attempt == 1:
                    raise   # 두 번째도 실패하면 상위로 전파
        return []

    def batch_transcribe(self, wav_paths: list[Path],
                         language: str | None = None) -> list[dict]:
        """[항목6] 여러 파일 일괄 STT (모델 1회 로드, 순차 처리).

        Args:
            wav_paths: 처리할 WAV 파일 경로 목록
            language:  None = 자동 감지

        Returns:
            [{"path": Path, "segments": [{start, end, text}], "stt_status": str}, ...]
              stt_status: "ok" | "no_speech"
        """
        results = []
        for wav_path in wav_paths:
            segs = self.transcribe(wav_path, language=language)
            has_speech = any(s["text"].strip() for s in segs)
            results.append({
                "path":       wav_path,
                "segments":   segs,
                "stt_status": "ok" if has_speech else "no_speech",
            })
        return results

    def unload(self):
        del self.model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
