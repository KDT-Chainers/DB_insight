import { useEffect, useState } from 'react'
import AnimatedOrb from '../components/AnimatedOrb'

const STAGE_LABELS = {
  init: '백엔드 초기화 중',
  engine_load: '검색 엔진 로딩 중',
  image_search: '이미지 모델 워밍업',
  doc_search: '문서 모델 워밍업',
  av_search: '영상·음성 모델 워밍업',
  done: '준비 완료',
}

export default function SplashOrb() {
  const [status, setStatus] = useState({ ready: false, stage: 'init', elapsed: 0 })

  useEffect(() => {
    let alive = true
    const fetchStatus = async () => {
      try {
        const r = await fetch('http://127.0.0.1:5001/api/warmup-status')
        if (!r.ok) return
        const j = await r.json()
        if (alive) setStatus(j)
      } catch (_e) { /* 백엔드 미준비 — 무시 */ }
    }
    fetchStatus()
    const id = setInterval(fetchStatus, 800)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const label = STAGE_LABELS[status.stage] || 'Loading'
  const elapsed = status.elapsed ? `${status.elapsed.toFixed(1)}s` : ''

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#070d1f]">
      <div className="studio-bridge-bg pointer-events-none absolute inset-0" />

      <div className="absolute inset-0 flex items-center justify-center">
        <div className="pointer-events-none absolute inset-0">
          <AnimatedOrb
            layout="fill"
            interactive={false}
            hideCenterUI
          />
        </div>
      </div>

      <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 translate-y-[126px] text-center">
        <p id="splash-status" className="text-xs tracking-[0.08em] text-white/70">
          {label}{elapsed ? ` · ${elapsed}` : ''}
        </p>
        {status.ready && (
          <p className="mt-1 text-[10px] tracking-[0.1em] text-emerald-300/70">
            ✓ Ready
          </p>
        )}
      </div>
    </div>
  )
}
