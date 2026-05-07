// 파일 트리에서 '이미 인덱싱됨' 시각 배지.
// indexed=false 또는 정보 없음이면 아무것도 렌더하지 않는다 (높이 0).

const DOMAIN_KO = { doc: '문서', image: '이미지', video: '동영상', audio: '음성' }

export default function IndexedBadge({ indexed, domain }) {
  if (!indexed) return null
  const label = DOMAIN_KO[domain] ?? domain ?? ''
  return (
    <span
      title={`이미 인덱싱됨${label ? ` · ${label}` : ''}`}
      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 text-xs font-bold shrink-0"
    >
      <span
        className="material-symbols-outlined text-xs"
        style={{ fontVariationSettings: '"FILL" 1' }}
      >
        check_circle
      </span>
      <span>완료</span>
    </span>
  )
}
