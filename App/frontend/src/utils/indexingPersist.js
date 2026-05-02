// 인덱싱 페이지 상태 영속화 — localStorage.
// 사용자가 앱 재시작 시 이전에 선택했던 raw_DB 폴더와 체크 상태를 복원.

const KEY = 'dbinsight.indexing.v1'

export function saveIndexingState({ rootPath, checkedPaths }) {
  try {
    const payload = {
      rootPath: rootPath || '',
      // Set 은 직렬화 불가 → Array 변환
      checkedPaths: Array.from(checkedPaths || []),
      ts: Date.now(),
    }
    localStorage.setItem(KEY, JSON.stringify(payload))
  } catch (e) {
    // Quota exceeded / private mode 등 — 조용히 실패 (영속화는 best-effort)
    console.warn('[indexingPersist] save failed:', e?.message)
  }
}

export function loadIndexingState() {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    return {
      rootPath: data.rootPath || '',
      checkedPaths: new Set(data.checkedPaths || []),
      ts: data.ts || 0,
    }
  } catch {
    return null
  }
}

export function clearIndexingState() {
  try { localStorage.removeItem(KEY) } catch {}
}

// ── 진행 중인 인덱싱 job 추적 ─────────────────────────────────
// 사용자가 워크스페이스 등 다른 페이지로 이동 → DataIndexing unmount →
// jobId state 손실. 다시 돌아오면 진행 상황을 복원할 수 없어 "취소된 듯"
// 보임. 실제로는 backend 계속 실행 중. 이 함수들이 jobId 영속화 + 재진입
// 시 backend status 재조회로 진행 화면 자동 복구.

const JOB_KEY = 'dbinsight.activeJob.v1'

export function saveActiveJob(jobId) {
  try {
    if (jobId) {
      localStorage.setItem(JOB_KEY, JSON.stringify({ jobId, ts: Date.now() }))
    } else {
      localStorage.removeItem(JOB_KEY)
    }
  } catch {}
}

export function loadActiveJob() {
  try {
    const raw = localStorage.getItem(JOB_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    // 24h 이상 stale 엔트리는 폐기 (서버 재시작 후 잔여)
    if (Date.now() - (data.ts || 0) > 24 * 3600 * 1000) {
      localStorage.removeItem(JOB_KEY)
      return null
    }
    return data.jobId || null
  } catch {
    return null
  }
}

export function clearActiveJob() {
  try { localStorage.removeItem(JOB_KEY) } catch {}
}
