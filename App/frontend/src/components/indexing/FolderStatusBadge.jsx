// 폴더 우측에 표시되는 상태 배지.
// 상태 4단계 + orphan(빨강) 부가 표시:
//   - 전부 인덱싱 완료     → 초록 "N ✓"
//   - 부분 인덱싱           → 파랑 "i/N"   (i = indexed, N = total subtree)
//   - 전부 신규             → 황색 "신규 N"
//   - 미펼침/미스캔        → 회색 "N"      (childCount = 1단계 자식 수)
//   - orphan(임베딩 후 삭제) → 빨강 "삭제 K" 별도 칩 (위 배지와 동시 노출)

export default function FolderStatusBadge({ subtreeFiles, indexedMap, childCount, orphanCount }) {
  const total = subtreeFiles?.length ?? 0
  const indexedCount = total > 0
    ? subtreeFiles.filter(p => indexedMap?.[p]?.indexed).length
    : 0
  const newCount = total - indexedCount

  let main = null
  if (total === 0 && childCount != null) {
    main = (
      <span className="shrink-0 px-2 py-0.5 rounded-full text-xs font-bold bg-white/5 text-on-surface-variant/40">
        {childCount}
      </span>
    )
  } else if (total > 0) {
    if (indexedCount === total) {
      main = (
        <span title={`${total}개 모두 인덱싱 완료`}
              className="shrink-0 inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400">
          <span className="material-symbols-outlined text-xs" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>
          <span>{total}</span>
        </span>
      )
    } else if (indexedCount === 0) {
      main = (
        <span title={`${newCount}개 모두 신규 (인덱싱 필요)`}
              className="shrink-0 inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/15 text-amber-400">
          <span className="material-symbols-outlined text-xs">fiber_new</span>
          <span>신규 {newCount}</span>
        </span>
      )
    } else {
      main = (
        <span title={`인덱싱 ${indexedCount}/${total}, 신규 ${newCount}`}
              className="shrink-0 inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-bold bg-[#85adff]/15 text-[#85adff]">
          <span>{indexedCount}/{total}</span>
        </span>
      )
    }
  }

  const orphan = (orphanCount && orphanCount > 0) ? (
    <span title={`임베딩 후 raw_DB 에서 삭제된 파일 ${orphanCount}개`}
          className="shrink-0 inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-bold bg-red-500/15 text-red-400">
      <span className="material-symbols-outlined text-xs">delete_forever</span>
      <span>삭제 {orphanCount}</span>
    </span>
  ) : null

  if (!main && !orphan) return null
  return (
    <span className="shrink-0 flex items-center gap-1">
      {main}
      {orphan}
    </span>
  )
}
