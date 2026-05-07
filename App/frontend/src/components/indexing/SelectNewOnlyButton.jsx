// '신규만 선택' 버튼.
// 현재까지 트리에 펼쳐진(=indexedMap 에 등재된) 파일 중 미인덱싱 파일만 체크.
// 사용자가 "이미 임베딩된 파일은 다시 안 해도 되는데, 새 것만 빨리 고르고 싶다" 는 의도를 한 번 클릭으로 처리.

export default function SelectNewOnlyButton({ indexedMap, onApply }) {
  const allPaths = Object.keys(indexedMap || {})
  const newPaths = allPaths.filter(p => !indexedMap[p]?.indexed)
  const newCount = newPaths.length
  const totalCount = allPaths.length
  const disabled = totalCount === 0

  return (
    <button
      onClick={() => onApply(newPaths)}
      disabled={disabled}
      className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-primary/10 text-primary text-base font-bold uppercase hover:brightness-125 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
      title={
        disabled
          ? '폴더를 펼치면 활성화됩니다'
          : `미인덱싱 ${newCount}개만 선택 (전체 펼친 파일 ${totalCount}개)`
      }
    >
      <span className="material-symbols-outlined text-base">filter_alt</span>
      <span>신규만 선택 ({newCount})</span>
    </button>
  )
}
