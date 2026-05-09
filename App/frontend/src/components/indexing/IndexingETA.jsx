import { useState, useEffect } from 'react'
import { fmtDuration, fmtETA, fmtCompletionTime } from '../../utils/etaUtils'

export default function IndexingETA({ data, loading, remainingSec, isRunning, processedCount, startedAt }) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!isRunning && remainingSec == null) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [isRunning, remainingSec])

  const elapsedSec = startedAt ? Math.max(0, Date.now() / 1000 - startedAt) : null

  if (isRunning || remainingSec != null) {
    const etaText = fmtETA(remainingSec)

    if (processedCount === 0) {
      return (
        <div className="mt-2 pt-2 border-t border-outline-variant/15">
          <p className="text-base text-on-surface-variant/60 font-bold uppercase tracking-widest mb-1">
            완료 예정
          </p>
          <p className="text-lg font-black text-on-surface leading-none">
            {etaText ?? '계산 중...'}
          </p>
          {elapsedSec != null && elapsedSec >= 1 && (
            <p className="text-sm text-on-surface-variant/50 mt-1">
              경과 {fmtDuration(elapsedSec)}
            </p>
          )}
        </div>
      )
    }

    return (
      <div className="mt-2 pt-2 border-t border-outline-variant/15">
        <p className="text-base text-on-surface-variant/60 font-bold uppercase tracking-widest mb-1">
          완료 예정
        </p>
        <p className="text-lg font-black text-on-surface leading-none">
          {etaText ?? '계산 중...'}
        </p>
      </div>
    )
  }

  if (!data) return null
  const total = data.total_seconds ?? 0
  const skipped = data.skipped_count ?? 0
  const fresh = data.new_count ?? 0
  const unsup = data.unsupported ?? 0
  const etaText = loading ? '계산 중...' : (fmtCompletionTime(total) ?? fmtDuration(total))
  const durationText = loading ? '' : fmtDuration(total)
  const subtitle = loading
    ? ' '
    : `약 ${durationText} · 신규 ${fresh} · 건너뜀 ${skipped}${unsup ? ` · 미지원 ${unsup}` : ''}`

  return (
    <div className="mt-2 pt-2 border-t border-outline-variant/15">
      <p className="text-base text-on-surface-variant/60 font-bold uppercase tracking-widest mb-1">
        완료 예정
      </p>
      <p className="text-lg font-black text-on-surface leading-none">{etaText}</p>
      <p className="text-sm text-on-surface-variant/50 mt-1">{subtitle}</p>
    </div>
  )
}
