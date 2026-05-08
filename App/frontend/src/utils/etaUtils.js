export function fmtCompletionTime(remainingSec) {
  if (remainingSec == null || !isFinite(remainingSec) || remainingSec < 0) return null
  const eta = new Date(Date.now() + remainingSec * 1000)
  return eta.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
}

// 1분 미만: "약 Xs" / 1분 이상: "오후 3:47 완료 예정"
export function fmtETA(remainingSec) {
  if (remainingSec == null || !isFinite(remainingSec) || remainingSec < 0) return null
  if (remainingSec < 60) return `약 ${Math.max(1, Math.round(remainingSec))}초`
  return fmtCompletionTime(remainingSec)
}

export function fmtDuration(sec) {
  if (sec == null || !isFinite(sec) || sec < 0) return '—'
  if (sec < 1) return '< 1s'
  const total = Math.round(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m`
  return `${s}s`
}

const _DOC_EXTS   = new Set(['.pdf','.docx','.doc','.hwp','.hwpx','.pptx','.ppt','.txt','.md','.html','.htm','.xlsx','.xls'])
const _IMAGE_EXTS = new Set(['.jpg','.jpeg','.png','.webp','.gif','.bmp','.tif','.tiff'])
const _VIDEO_EXTS = new Set(['.mp4','.mov','.mkv','.avi','.webm','.flv','.m4v'])
const _AUDIO_EXTS = new Set(['.mp3','.wav','.m4a','.flac','.ogg','.aac','.wma','.opus'])

function _inferType(path) {
  const ext = '.' + (path.split('.').pop() ?? '').toLowerCase()
  if (_DOC_EXTS.has(ext))   return 'doc'
  if (_IMAGE_EXTS.has(ext)) return 'image'
  if (_VIDEO_EXTS.has(ext)) return 'video'
  if (_AUDIO_EXTS.has(ext)) return 'audio'
  return null
}

/**
 * Level 3 하이브리드 ETA.
 * @param {object} p
 * @param {number}  p.processed    완료 파일 수
 * @param {number}  p.total        전체 파일 수
 * @param {number}  p.elapsedSec   잡 시작 후 경과 초
 * @param {number|null} p.estimateSec  백엔드 pre-estimate 총 초
 * @param {{current:number}} p.factorRef  EWMA 상태 ref (잡 시작 시 1.0 초기화)
 * @param {Array}  [p.results]     jobStatus.results 배열
 * @param {object} [p.byType]      estimateData.by_type
 * @returns {number|null}
 */
export function computeRemainingETA({ processed, total, elapsedSec, estimateSec, factorRef, results, byType }) {
  if (!isFinite(total) || total <= 0) return null
  if (processed >= total) return 0
  if (!isFinite(elapsedSec) || elapsedSec < 0.5) {
    return (estimateSec > 0 && isFinite(estimateSec)) ? estimateSec : null
  }

  const fraction = processed / total

  if (estimateSec > 0 && isFinite(estimateSec)) {
    let avgEstByType = null
    if (byType && Object.keys(byType).length > 0) {
      avgEstByType = {}
      for (const [type, data] of Object.entries(byType)) {
        if (data.count > 0) avgEstByType[type] = data.seconds / data.count
      }
    }

    const fallbackPerFile = estimateSec / total
    let estimatedWorkDone = 0

    const completed = results?.filter(r =>
      r.status === 'done' || r.status === 'error' || r.status === 'skipped'
    ) ?? []

    if (avgEstByType && completed.length > 0) {
      for (const r of completed) {
        if (r.status === 'skipped') { estimatedWorkDone += 0.05; continue }
        const type = r.file_type ?? _inferType(r.path)
        estimatedWorkDone += (type && avgEstByType[type] != null)
          ? avgEstByType[type]
          : fallbackPerFile
      }
    } else {
      estimatedWorkDone = estimateSec * fraction
    }

    if (estimatedWorkDone > 0.2 && processed >= 1) {
      const raw = Math.max(0.05, Math.min(20, elapsedSec / estimatedWorkDone))
      factorRef.current = 0.15 * raw + 0.85 * factorRef.current
    }

    const remainingEstWork = Math.max(0, estimateSec - estimatedWorkDone)

    if (processed >= 1 && estimatedWorkDone > 0.2) {
      // EWMA factor 대신 실측 rate 직접 사용 → estimate 크기에 무관하게 정확
      const actualRate = elapsedSec / estimatedWorkDone
      return Math.max(0, remainingEstWork * actualRate)
    }

    return Math.max(0, remainingEstWork * factorRef.current)
  }

  if (processed <= 0) return null
  const rate = processed / elapsedSec
  return rate > 0 ? Math.max(0, (total - processed) / rate) : null
}
