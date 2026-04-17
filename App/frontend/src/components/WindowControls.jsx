/**
 * WindowControls — 커스텀 윈도우 버튼 (최소화 / 최대화 / 닫기)
 * frame:false 인 Electron 환경에서 타이틀바 대체용으로 사용.
 * 부모 헤더에 `style={{ WebkitAppRegion: 'drag' }}` 를 주고,
 * 이 컴포넌트 자체는 no-drag 영역으로 지정됩니다.
 */
export default function WindowControls() {
  const minimize = () => window.electronAPI?.windowMinimize()
  const maximize = () => window.electronAPI?.windowMaximize()
  const close    = () => window.electronAPI?.windowClose()

  return (
    <div
      className="flex items-center gap-1"
      style={{ WebkitAppRegion: 'no-drag' }}
    >
      {/* 최소화 */}
      <button
        onClick={minimize}
        title="최소화"
        className="w-7 h-7 flex items-center justify-center rounded-full text-[#a5aac2] hover:bg-white/10 hover:text-[#dfe4fe] transition-colors"
      >
        <span className="material-symbols-outlined text-[15px]">remove</span>
      </button>

      {/* 최대화 / 복원 */}
      <button
        onClick={maximize}
        title="최대화"
        className="w-7 h-7 flex items-center justify-center rounded-full text-[#a5aac2] hover:bg-white/10 hover:text-[#dfe4fe] transition-colors"
      >
        <span className="material-symbols-outlined text-[13px]">crop_square</span>
      </button>

      {/* 닫기 */}
      <button
        onClick={close}
        title="닫기"
        className="w-7 h-7 flex items-center justify-center rounded-full text-[#a5aac2] hover:bg-red-500/80 hover:text-white transition-colors"
      >
        <span className="material-symbols-outlined text-[15px]">close</span>
      </button>
    </div>
  )
}
