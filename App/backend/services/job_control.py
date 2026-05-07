"""인덱싱 작업의 즉시 중단을 위한 child process 컨트롤러.

문제 배경:
  routes/index.py 의 _run_job 은 stop_flag 만 체크 → 단계 사이에서만 폴링.
  ffmpeg 프레임 추출, faster-whisper STT 등 blocking native 호출은 stop_flag
  를 신경 쓰지 않으므로, 사용자가 "중단" 클릭해도 현재 파일이 끝날 때까지
  무한정 대기하는 UX 문제 발생.

해결:
  /stop 시 backend 프로세스의 child(ffmpeg/cuvid 등)를 OS 시그널로 종료.
  blocking 호출이 즉시 예외와 함께 반환 → embedder 가 status="error" 로
  마무리 → _run_job 이 stop_flag 보고 loop 종료.

설계 원칙:
  - psutil 만 사용 (이미 설치됨, 7.1.2)
  - 백엔드 자기 자신은 절대 죽이지 않음 (children 만)
  - 안전: 타임아웃 후 SIGKILL 전, SIGTERM 우선 시도
  - 멱등: 여러 번 호출되어도 안전 (이미 죽은 프로세스는 무시)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ffmpeg 와 그 외 임베딩 파이프라인이 spawn 할 수 있는 자식 프로세스 이름.
# Windows .exe / Unix 모두 고려.
_KILL_TARGET_NAMES = {
    "ffmpeg", "ffmpeg.exe",
    "ffprobe", "ffprobe.exe",
    "cuvid", "h264_cuvid",  # NVDEC 가속 시 발생 가능
}


def kill_indexing_subprocesses(timeout: float = 2.0) -> int:
    """현재 백엔드 프로세스의 child 중 임베딩 관련 자식들을 종료.

    Returns:
        종료된 프로세스 수.
    """
    try:
        import psutil
    except ImportError:
        logger.warning("[job_control] psutil 미설치 — child kill 스킵")
        return 0

    me = psutil.Process(os.getpid())
    targets: list = []
    try:
        # children(recursive=True) 으로 손자까지 포함
        for child in me.children(recursive=True):
            try:
                name = (child.name() or "").lower()
                if name in _KILL_TARGET_NAMES:
                    targets.append(child)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logger.warning(f"[job_control] child 열거 실패: {e}")
        return 0

    if not targets:
        return 0

    # 1단계: SIGTERM (graceful)
    for p in targets:
        try:
            p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 잠시 대기 후 살아남은 것은 SIGKILL
    gone, alive = psutil.wait_procs(targets, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    killed = len(targets)
    logger.info(f"[job_control] 인덱싱 자식 프로세스 {killed}개 종료")
    return killed
