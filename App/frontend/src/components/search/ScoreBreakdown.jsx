// 검색 결과 카드의 점수 분해 미니 패널.
// /api/search 응답에 있는 dense / lexical / asf / z_score / rerank_score 를
// 막대 차트로 시각화. 라이브러리 의존 없음(div + CSS).
//
// admin.html 의 metrics 패널과 동일한 정보를 메인 검색 결과 detail 뷰에 노출.
// 사용자가 "왜 이 결과가 상위인가" 를 즉시 확인 가능.

const FIELDS = [
  { key: 'dense',        label: 'Dense',     color: 'bg-emerald-500/70', desc: 'Hermitian 3축 복소 점수' },
  { key: 'lexical',      label: 'Lexical',   color: 'bg-[#85adff]/70',   desc: 'BGE-M3 sparse 어휘 일치' },
  { key: 'asf',          label: 'ASF',       color: 'bg-[#ac8aff]/70',   desc: 'Attention-Similarity-Filter' },
  { key: 'rerank_score', label: 'Rerank',    color: 'bg-amber-400/70',   desc: 'BGE-v2-m3 cross-encoder' },
  { key: 'z_score',      label: 'z-score',   color: 'bg-pink-400/70',    desc: '쿼리 분포 표준화' },
]

function fmt(v) {
  if (v == null) return '—'
  if (typeof v !== 'number') return String(v)
  return v.toFixed(3)
}

function normalize(v, field) {
  if (v == null || typeof v !== 'number') return 0
  if (field === 'rerank_score') {
    // sigmoid 로 [0,1] 정규화 (음수 = 부적합 → 0 부근)
    return 1 / (1 + Math.exp(-v))
  }
  if (field === 'z_score') {
    // [-3, +3] → [0, 1] clamp
    return Math.max(0, Math.min(1, (v + 3) / 6))
  }
  // dense/lexical/asf — 보통 [0, 1] 범위
  return Math.max(0, Math.min(1, v))
}

export default function ScoreBreakdown({ result }) {
  if (!result) return null
  const present = FIELDS.filter(f => result[f.key] != null)
  if (present.length === 0) return null

  return (
    <div className="bg-[#0b1220] rounded-md p-3 border border-[#334155] space-y-2">
      <div className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-on-surface-variant/60 font-bold">
        <span className="material-symbols-outlined text-base">analytics</span>
        <span>점수 구성</span>
      </div>
      <div className="space-y-1.5">
        {present.map(f => {
          const v = result[f.key]
          const w = (normalize(v, f.key) * 100).toFixed(0)
          return (
            <div key={f.key} className="flex items-center gap-2 text-xs" title={f.desc}>
              <span className="w-16 shrink-0 text-on-surface-variant/70 font-bold">{f.label}</span>
              <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
                <div
                  className={`h-full ${f.color} transition-all`}
                  style={{ width: `${w}%` }}
                />
              </div>
              <span className="w-12 shrink-0 text-right tabular-nums font-mono text-on-surface">
                {fmt(v)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
