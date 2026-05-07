"""VRAM 주기적 정리 — RTX 4070 Laptop 8GB 한계 관리.

배경:
  여러 모델(SigLIP2 + DINOv2 + BGE-M3 + Whisper + Qwen-VL + Reranker)이
  같은 프로세스에 상주 시 VRAM 공유. PyTorch caching allocator 가 활용 끝난
  메모리도 즉시 반환하지 않고 reserved 영역에 보관 → 다른 모델 로드 시 OOM
  유발. `torch.cuda.empty_cache()` 호출로 reserved → free 복원 가능.

적용 시점:
  1. 인덱싱 파일 1개 처리 후 (단계 사이 누적된 임시 텐서 정리)
  2. 큰 모델 unload 후 (av_embed.py 의 SigLIP2/DINOv2 close 시점)
  3. /api/index/start 진입 시 1회 (이전 검색 세션 잔여 정리)

설계:
  - 동기 호출만 (asyncio 불필요, ms 단위)
  - torch 미설치 환경 안전 (try/except)
  - 환경변수 OMC_DISABLE_VRAM_JANITOR=1 로 OFF
  - 임계값 기반 트리거 옵션 — `cleanup_if_above(threshold_mb=6000)`
    → reserved 가 임계 이상일 때만 정리 (불필요한 호출 회피)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get("OMC_DISABLE_VRAM_JANITOR", "").strip().lower() not in ("1", "true", "yes")


def _vram_stats() -> tuple[float, float] | None:
    """(reserved_MB, allocated_MB) 또는 None(미사용 환경)."""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        reserved  = torch.cuda.memory_reserved()  / (1024 * 1024)
        allocated = torch.cuda.memory_allocated() / (1024 * 1024)
        return reserved, allocated
    except Exception:
        return None


def cleanup() -> dict:
    """무조건 empty_cache + gc.collect.

    Returns:
        { "freed_mb": float, "reserved_before_mb": float, "reserved_after_mb": float }
    """
    if not _enabled():
        return {"freed_mb": 0.0, "skipped": True}
    try:
        import gc
        import torch
    except ImportError:
        return {"freed_mb": 0.0, "skipped": True}

    if not torch.cuda.is_available():
        return {"freed_mb": 0.0, "skipped": True}

    before = torch.cuda.memory_reserved() / (1024 * 1024)
    gc.collect()
    torch.cuda.empty_cache()
    after = torch.cuda.memory_reserved() / (1024 * 1024)
    freed = max(0.0, before - after)
    return {
        "freed_mb": round(freed, 1),
        "reserved_before_mb": round(before, 1),
        "reserved_after_mb": round(after, 1),
    }


def cleanup_if_above(threshold_mb: float = 6000.0) -> dict:
    """reserved 가 임계 이상일 때만 정리. 매 파일 호출 시 부담 최소화.

    8GB GPU 에서 6GB 임계치 = 75% 사용 시 정리.
    """
    if not _enabled():
        return {"triggered": False, "skipped": True}
    stats = _vram_stats()
    if stats is None:
        return {"triggered": False, "skipped": True}
    reserved, allocated = stats
    if reserved < threshold_mb:
        return {"triggered": False, "reserved_mb": round(reserved, 1)}
    result = cleanup()
    result["triggered"] = True
    return result


def vram_summary() -> str:
    """디버깅용 한 줄 요약 — 'VRAM: 4523/8192 MB reserved (3210 alloc)'"""
    stats = _vram_stats()
    if stats is None:
        return "VRAM: N/A"
    reserved, allocated = stats
    try:
        import torch
        total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
    except Exception:
        total = 0.0
    return f"VRAM: {reserved:.0f}/{total:.0f} MB reserved ({allocated:.0f} alloc)"


def aggressive_cleanup() -> dict:
    """공격적 VRAM 정리 — 큰 모델 로드 직전에 호출.

    cleanup() 보다 강함:
      1. gc.collect() 2회 (cycle GC 보장)
      2. torch.cuda.empty_cache()
      3. torch.cuda.synchronize() — 진행 중 커널 완료 대기
      4. ipc_collect() — IPC 메모리 핸들 회수

    SigLIP2 / DINOv2 / Whisper 같은 GB-급 모델 로드 직전에 호출하여
    이전 모델의 deferred deallocation 잔여를 확실히 회수.
    """
    if not _enabled():
        return {"freed_mb": 0.0, "skipped": True}
    try:
        import gc
        import torch
    except ImportError:
        return {"freed_mb": 0.0, "skipped": True}
    if not torch.cuda.is_available():
        return {"freed_mb": 0.0, "skipped": True}

    before = torch.cuda.memory_reserved() / (1024 * 1024)
    gc.collect()
    gc.collect()  # 2회: 순환 참조의 한 단계 더 따라감
    try:
        torch.cuda.synchronize()
    except Exception:
        pass
    torch.cuda.empty_cache()
    try:
        torch.cuda.ipc_collect()
    except Exception:
        pass
    after = torch.cuda.memory_reserved() / (1024 * 1024)
    freed = max(0.0, before - after)
    return {
        "freed_mb": round(freed, 1),
        "reserved_before_mb": round(before, 1),
        "reserved_after_mb": round(after, 1),
    }


def ensure_free(target_free_mb: float = 4000.0) -> dict:
    """원하는 free VRAM 확보 시도. 부족하면 aggressive_cleanup 자동 호출.

    Args:
        target_free_mb: 확보하고자 하는 free 메모리 (MB).
                        SigLIP2(~1.3G) + DINOv2(~1G) + Whisper(~3G) 로드용 = 5G+ 필요.

    Returns:
        { "ok": bool, "free_mb": float, "cleanup": dict | None }
    """
    if not _enabled():
        return {"ok": True, "skipped": True}
    try:
        import torch
    except ImportError:
        return {"ok": True, "skipped": True}
    if not torch.cuda.is_available():
        return {"ok": True, "skipped": True}

    total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
    reserved = torch.cuda.memory_reserved() / (1024 * 1024)
    free_mb = total - reserved
    if free_mb >= target_free_mb:
        return {"ok": True, "free_mb": round(free_mb, 1), "cleanup": None}

    cleanup_result = aggressive_cleanup()
    reserved2 = torch.cuda.memory_reserved() / (1024 * 1024)
    free_mb2 = total - reserved2
    return {
        "ok": free_mb2 >= target_free_mb,
        "free_mb": round(free_mb2, 1),
        "cleanup": cleanup_result,
    }
