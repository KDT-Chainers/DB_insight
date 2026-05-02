// 검색 결과를 도메인별로 필터링하는 칩 그룹.
// 검색창 자체는 손대지 않고, 결과 영역 헤더 바로 아래에 마운트.
// 백엔드 /api/search?type=doc|image|video|audio 파라미터와 1:1 매핑.
//
// 동작:
//   - 단일 선택 (한 번에 하나의 도메인만), "전체" 클릭 시 해제
//   - 변경 즉시 onChange(value) 콜백 → 부모가 검색 재실행

const ITEMS = [
  { value: '',      label: '전체',   icon: 'apps',         color: 'text-on-surface' },
  { value: 'doc',   label: '문서',   icon: 'description',  color: 'text-[#85adff]' },
  { value: 'image', label: '이미지', icon: 'image',        color: 'text-emerald-400' },
  { value: 'video', label: '동영상', icon: 'movie',        color: 'text-[#ac8aff]' },
  { value: 'audio', label: '음성',   icon: 'volume_up',    color: 'text-amber-400' },
]

export default function DomainFilter({ value, onChange, counts }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {ITEMS.map(item => {
        const active = value === item.value
        const count = item.value ? (counts?.[item.value] ?? null) : (counts?._total ?? null)
        return (
          <button
            key={item.value || 'all'}
            onClick={() => onChange(item.value)}
            title={item.value ? `${item.label}만 보기` : '도메인 필터 해제'}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-bold transition-all
              ${active
                ? 'bg-primary text-on-primary shadow-md'
                : 'bg-white/5 text-on-surface-variant hover:bg-white/10'}`}
          >
            <span className={`material-symbols-outlined text-base ${active ? '' : item.color}`}>
              {item.icon}
            </span>
            <span>{item.label}</span>
            {count != null && (
              <span className={`text-xs px-1.5 py-0.5 rounded-full
                ${active ? 'bg-on-primary/20' : 'bg-white/5'}`}>
                {count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
