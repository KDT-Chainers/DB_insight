import { useNavigate } from 'react-router-dom'
import WindowControls from '../components/WindowControls'
import AnimatedOrb from '../components/AnimatedOrb'
import AmbientPageBackdrop from '../components/AmbientPageBackdrop'
import TeamLogoMark from '../components/TeamLogoMark'

/**
 * v0 AIHero 스타일 인트로 (히어로 + 오브).
 * 앱 기본 진입은 / (보안 인증). 이 화면은 #/welcome 에서만 연다.
 */
export default function LandingHome() {
  const navigate = useNavigate()

  return (
    <div className="relative min-h-screen overflow-x-hidden overflow-y-auto font-body text-on-surface">
      <AmbientPageBackdrop />

      <div
        className="titlebar-chrome fixed left-0 right-0 top-0 z-[9999] flex h-8 items-center justify-end px-2"
        style={{ WebkitAppRegion: 'drag' }}
      >
        <div style={{ WebkitAppRegion: 'no-drag' }}>
          <WindowControls />
        </div>
      </div>

      <header className="relative z-10 flex items-center justify-between px-6 pb-2 pt-10 md:px-8">
        <TeamLogoMark className="!h-9 !w-9 rounded-xl md:!h-10 md:!w-10" />
        <nav className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate('/setup')}
            className="rounded-full border border-white/10 bg-surface-container-high/50 px-3 py-2 text-xs font-medium text-on-surface-variant backdrop-blur-md transition-colors hover:bg-surface-container-high/70 hover:text-primary md:px-4 md:text-sm"
          >
            초기 설정
          </button>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-on-primary-fixed transition-colors hover:bg-primary-dim md:px-5"
          >
            로그인
          </button>
        </nav>
      </header>

      <main className="relative z-10 flex min-h-[calc(100vh-2rem)] flex-col items-center justify-center overflow-visible px-6 pb-16 pt-6 md:px-8">
        <div className="mb-6 text-center">
          <h1 className="mb-2 text-3xl font-light tracking-tight text-on-surface md:text-4xl lg:text-5xl">
            Local Intelligence
          </h1>
          <p className="text-base text-on-surface-variant md:text-lg">Your Data Stays Yours</p>
          <p className="mt-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">로컬 인텔리전스 프로토콜</p>
        </div>

        <div className="my-4 overflow-visible md:my-8">
          <AnimatedOrb />
        </div>

        <button
          type="button"
          onClick={() => navigate('/')}
          className="group mt-6 flex items-center gap-3 rounded-full border border-outline-variant/20 bg-surface-container-high px-8 py-3 text-sm font-bold tracking-wide text-on-surface-variant transition-all duration-300 hover:bg-surface-container-highest hover:text-on-surface active:scale-[0.98]"
        >
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden />
          시스템 시작
          <span
            className="material-symbols-outlined text-lg transition-transform group-hover:translate-x-1"
            style={{ fontVariationSettings: '"FILL" 0' }}
          >
            arrow_forward
          </span>
        </button>
      </main>
    </div>
  )
}
