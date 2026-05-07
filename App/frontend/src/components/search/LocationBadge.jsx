// 검색 결과 카드에 표시할 위치 배지.
// Doc: "p.12 · L.45" / Video·Audio: "2:06" 형식의 작은 칩.
// snippet 이 있으면 tooltip 으로 매칭 본문 미리보기 제공.

export default function LocationBadge({ location, fileType }) {
  if (!location) return null

  if (fileType === 'doc' && location.page_label) {
    const label = location.line_label
      ? `${location.page_label} · ${location.line_label}`
      : location.page_label
    const tip = location.snippet
      ? `페이지 ${location.page}${location.line ? `, ${location.line}번째 줄` : ''} — "${location.snippet}"`
      : `이 페이지에서 매칭됨 (페이지 ${location.page})`
    return (
      <span
        title={tip}
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-[#85adff]/15 text-[#85adff] text-xs font-bold shrink-0"
      >
        <span className="material-symbols-outlined text-xs" style={{ fontVariationSettings: '"FILL" 1' }}>
          description
        </span>
        <span>{label}</span>
      </span>
    )
  }

  if ((fileType === 'video' || fileType === 'audio') && location.timestamp_label) {
    const tip = location.snippet
      ? `${location.timestamp_label} 지점 — "${location.snippet}"`
      : `이 시점에서 매칭됨 (${location.timestamp_label})`
    return (
      <span
        title={tip}
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-[#ac8aff]/15 text-[#ac8aff] text-xs font-bold shrink-0"
      >
        <span className="material-symbols-outlined text-xs">schedule</span>
        <span>{location.timestamp_label}</span>
      </span>
    )
  }

  // [Image] 캡션 매칭 — snippet 있으면 표시
  if (fileType === 'image' && (location.snippet || location.caption)) {
    const text = location.snippet || location.caption
    const tip  = `이미지 캡션 매칭 — "${text}"`
    return (
      <span
        title={tip}
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-emerald-400/15 text-emerald-400 text-xs font-bold shrink-0"
      >
        <span className="material-symbols-outlined text-xs">format_quote</span>
        <span>캡션</span>
      </span>
    )
  }

  return null
}
