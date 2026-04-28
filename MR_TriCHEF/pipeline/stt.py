"""faster-whisper STT 래퍼 (GPU int8_float16).

[항목5] LoRA adapter_path 지원:
  WHISPER_ADAPTER_PATH 가 설정되면 faster-whisper의 local 모델로 로드.
  빈 문자열이면 기본 MODEL_WHISPER (large-v3) 사용.

[항목6] batch_transcribe() 추가:
  여러 파일을 순차 STT 후 결과 dict 목록 반환.
  faster-whisper 는 배치 병렬화 미지원이므로 순차 처리,
  단 한 번만 모델 로드 → 호출마다 로드하는 것 대비 VRAM 효율 개선.
"""
from __future__ import annotations

import gc
from pathlib import Path

import torch

from .paths import MODEL_WHISPER, WHISPER_ADAPTER_PATH


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

    def transcribe(self, wav_path: Path, language: str | None = None) -> list[dict]:
        """단일 파일 STT → [{start, end, text}, ...]"""
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
