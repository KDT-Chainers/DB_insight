/**
 * 전역 페이지 배경: 좌·우 하단 코너 radial + 하단 시안 밴드 (index.css `.app-depth-bg`).
 */
export default function AmbientPageBackdrop() {
  return (
    <div
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden app-depth-bg"
      aria-hidden="true"
    />
  )
}
