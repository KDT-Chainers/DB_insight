// 인덱싱 예상 소요 시간 표시 배지.
// 좌측 사이드바(선택 파일 카운트 아래) 에 마운트되어, checkedPaths 변경 시
// 백엔드 /api/index/estimate 응답을 기반으로 ETA 를 갱신한다.

function fmtDuration(sec) {
  if (sec == null || sec < 0) return '—'
  if (sec < 1) return '< 1s'
  const total = Math.round(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export default function IndexingETA({ data, loading }) {
  // data: { total_seconds, new_seconds, skip_seconds, skipped_count, new_count, unsupported, by_type }
  if (!data) return null
  // [Phase 2] 신규 파일 시간만 표시 (skip overhead 제외).
  // new_seconds 가 없는 구버전 응답은 total_seconds 폴백.
  const newSec  = data.new_seconds  ?? data.total_seconds ?? 0
  const skipSec = data.skip_seconds ?? 0
  const skipped = data.skipped_count ?? 0
  const fresh   = data.new_count    ?? 0
  const unsup   = data.unsupported  ?? 0

  const eta = loading ? '계산 중...' : fmtDuration(newSec)

  // 건너뜀이 있으면 "(+Xs)" 형태로 skip overhead 병기
  const skipNote = skipped > 0 ? ` (+${fmtDuration(skipSec)})` : ''
  const subtitle = loading
    ? ' '
    : `신규 ${fresh}${skipNote} · 건너뜀 ${skipped}${unsup ? ` · 미지원 ${unsup}` : ''}`

  return (
    <div className="mt-2 pt-2 border-t border-outline-variant/15">
      <p className="text-base text-on-surface-variant/60 font-bold uppercase tracking-widest mb-1">
        예상 시간
      </p>
      <p className="text-lg font-black text-on-surface leading-none">{eta}</p>
      <p className="text-sm text-on-surface-variant/50 mt-1">{subtitle}</p>
    </div>
  )
}
