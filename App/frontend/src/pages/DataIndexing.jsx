import { useNavigate } from 'react-router-dom'
import { useState, useCallback, useRef, useEffect } from 'react'
import WindowControls from '../components/WindowControls'
import { API_BASE as API } from '../api'
const TYPE_ICON  = { doc: 'description', video: 'movie', image: 'image', audio: 'volume_up' }
const TYPE_LABEL = { doc: '문서', video: '동영상', image: '이미지', audio: '음성' }
const TYPE_COLOR = { doc: 'text-[#85adff]', video: 'text-[#ac8aff]', image: 'text-emerald-400', audio: 'text-amber-400' }
const INDENT = 18 // px per depth level

async function scanPath(path) {
  const res = await fetch(`${API}/api/index/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.error ?? `HTTP ${res.status}`)
  }
  const data = await res.json()
  return data.items ?? data.files ?? []
}

async function startIndexing(filePaths) {
  const res = await fetch(`${API}/api/index/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ files: filePaths }),
  })
  if (!res.ok) throw new Error('Start failed')
  return res.json()
}

async function fetchStatus(jobId) {
  const res = await fetch(`${API}/api/index/status/${jobId}`)
  if (!res.ok) throw new Error('Status failed')
  return res.json()
}

async function stopIndexing(jobId) {
  await fetch(`${API}/api/index/stop/${jobId}`, { method: 'POST' })
}

// ── 파일 행 ─────────────────────────────────────────────
function FileRow({ item, depth, checked, onToggle, jobResult }) {
  const icon = TYPE_ICON[item.type] ?? 'insert_drive_file'
  const sizeKB = item.size != null ? (item.size / 1024).toFixed(1) : '-'
  const supported = item.type !== null

  let statusIcon = null
  if (jobResult) {
    if (jobResult.status === 'done')
      statusIcon = <span className="material-symbols-outlined text-emerald-400 text-base shrink-0" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>
    else if (jobResult.status === 'running') {
      const step  = jobResult.step
      const total = jobResult.step_total ?? 4
      statusIcon = (
        <div className="flex items-center gap-1.5 shrink-0">
          {step != null && (
            <span className="text-[10px] text-primary/60 font-bold tabular-nums">{step}/{total}</span>
          )}
          <span className="material-symbols-outlined text-primary text-base animate-spin">progress_activity</span>
        </div>
      )
    } else if (jobResult.status === 'error')
      statusIcon = <span className="material-symbols-outlined text-red-400 text-base shrink-0" style={{ fontVariationSettings: '"FILL" 1' }}>error</span>
    else
      statusIcon = <span className="material-symbols-outlined text-on-surface-variant/30 text-base shrink-0">schedule</span>
  }

  return (
    <div
      className={`flex items-center gap-2 py-1 pr-3 rounded-lg hover:bg-white/5 transition-colors group ${!supported ? 'opacity-40' : ''}`}
      style={{ paddingLeft: `${10 + depth * INDENT}px` }}
    >
      {/* 폴더 화살표 자리 맞춤 */}
      <span className="w-5 shrink-0" />
      <input
        type="checkbox"
        checked={checked}
        disabled={!supported}
        onChange={() => supported && onToggle(item.path)}
        className="w-3.5 h-3.5 rounded border-outline-variant bg-transparent text-primary focus:ring-0 focus:ring-offset-0 shrink-0 cursor-pointer"
      />
      <span className="material-symbols-outlined text-on-surface-variant text-[16px] shrink-0">{icon}</span>
      <span className="text-sm text-on-surface flex-1 truncate">{item.name}</span>
      <span className="text-xs text-on-surface-variant/30 shrink-0 group-hover:text-on-surface-variant/60">{sizeKB} KB</span>
      {statusIcon}
    </div>
  )
}

// ── 폴더 행 (lazy expand + 체크박스) ────────────────────
function FolderRow({ item, depth, checkedPaths, onToggle, onSetMany, jobResultMap }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [checkLoading, setCheckLoading] = useState(false)
  const [children, setChildren] = useState(null) // null = 아직 로드 안 함
  const checkboxRef = useRef(null)

  // 직접 파일 자식 목록 (loaded 시)
  const directFiles = (children ?? []).filter(i => i.kind === 'file' && i.type)
  const checkedCount = directFiles.filter(i => checkedPaths.has(i.path)).length
  const allChecked = directFiles.length > 0 && checkedCount === directFiles.length
  const someChecked = checkedCount > 0 && !allChecked

  // indeterminate 상태 적용
  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = someChecked
    }
  }, [someChecked])

  // 폴더 펼침 클릭
  const handleRowClick = async () => {
    if (!open && children === null) {
      setLoading(true)
      try {
        const items = await scanPath(item.path)
        setChildren(items)
      } catch {
        setChildren([])
      } finally {
        setLoading(false)
      }
    }
    setOpen(v => !v)
  }

  // 폴더 체크박스 클릭
  const handleFolderCheck = async (e) => {
    e.stopPropagation()
    const willCheck = e.target.checked || someChecked  // indeterminate → uncheck all

    let items = children
    if (items === null) {
      setCheckLoading(true)
      try {
        items = await scanPath(item.path)
        setChildren(items)
        setOpen(true)
      } catch {
        items = []
        setChildren([])
      } finally {
        setCheckLoading(false)
      }
    }

    const filePaths = items.filter(i => i.kind === 'file' && i.type).map(i => i.path)
    // indeterminate 상태면 uncheck all, 아니면 willCheck 따름
    const doCheck = someChecked ? false : willCheck
    onSetMany(filePaths, doCheck)
  }

  return (
    <>
      {/* 폴더 자신 */}
      <div
        className="flex items-center gap-2 py-1 pr-3 rounded-lg hover:bg-white/5 transition-colors cursor-pointer group"
        style={{ paddingLeft: `${10 + depth * INDENT}px` }}
      >
        {/* 펼침 화살표 */}
        <span
          onClick={handleRowClick}
          className="material-symbols-outlined text-on-surface-variant/50 text-[17px] shrink-0 w-5 hover:text-on-surface-variant transition-colors"
        >
          {loading || checkLoading ? 'hourglass_empty' : open ? 'expand_more' : 'chevron_right'}
        </span>

        {/* 폴더 체크박스 */}
        <input
          ref={checkboxRef}
          type="checkbox"
          checked={allChecked}
          onChange={handleFolderCheck}
          onClick={e => e.stopPropagation()}
          className="w-3.5 h-3.5 rounded border-outline-variant bg-transparent text-primary focus:ring-0 focus:ring-offset-0 shrink-0 cursor-pointer"
        />

        {/* 폴더 아이콘 + 이름 (클릭 시 펼침) */}
        <span
          onClick={handleRowClick}
          className="flex items-center gap-2 flex-1 min-w-0"
        >
          <span
            className="material-symbols-outlined text-[#85adff] text-[16px] shrink-0"
            style={{ fontVariationSettings: `"FILL" ${open ? 1 : 0}` }}
          >folder</span>
          <span className="text-sm text-on-surface flex-1 truncate font-medium">{item.name}</span>
        </span>

        {/* 자식 수 배지 */}
        {children !== null && (
          <span className="shrink-0 text-[10px] text-on-surface-variant/30 group-hover:text-on-surface-variant/60">
            {children.length}
          </span>
        )}
      </div>

      {/* 자식 목록 */}
      {open && children !== null && (
        <>
          {children.length === 0 && (
            <div
              className="py-1 text-xs text-on-surface-variant/30 italic"
              style={{ paddingLeft: `${10 + (depth + 1) * INDENT + 22}px` }}
            >
              비어 있음
            </div>
          )}
          {children.map(child =>
            child.kind === 'folder'
              ? <FolderRow
                  key={child.path} item={child} depth={depth + 1}
                  checkedPaths={checkedPaths} onToggle={onToggle}
                  onSetMany={onSetMany}
                  jobResultMap={jobResultMap}
                />
              : <FileRow
                  key={child.path} item={child} depth={depth + 1}
                  checked={checkedPaths.has(child.path)}
                  onToggle={onToggle}
                  jobResult={jobResultMap?.[child.path]}
                />
          )}
        </>
      )}
    </>
  )
}

// ── SVG 원형 프로그레스 링 ───────────────────────────────
function RingProgress({ pct, isDone, isError, isStopped }) {
  const r = 54, cx = 64, cy = 64
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - pct / 100)
  const color = isDone ? '#34d399' : isError ? '#f87171' : isStopped ? '#fbbf24' : '#85adff'
  const glow  = isDone ? 'rgba(52,211,153,0.4)' : isError ? 'rgba(248,113,113,0.4)' : isStopped ? 'rgba(251,191,36,0.4)' : 'rgba(133,173,255,0.5)'
  return (
    <svg width="128" height="128" viewBox="0 0 128 128">
      <defs>
        <filter id="ring-glow">
          <feGaussianBlur stdDeviation="3" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      {/* 배경 트랙 */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8"/>
      {/* 진행 링 */}
      <circle
        cx={cx} cy={cy} r={r} fill="none"
        stroke={color} strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${cx} ${cy})`}
        filter="url(#ring-glow)"
        style={{ transition: 'stroke-dashoffset 0.6s ease, stroke 0.4s ease',
                 filter: `drop-shadow(0 0 8px ${glow})` }}
      />
    </svg>
  )
}

// ── 인덱싱 진행 모달 ────────────────────────────────────
function IndexingModal({ rootPath, selectedCount, jobStatus, jobId, onClose, onStop }) {
  const total     = jobStatus?.total   ?? selectedCount
  const done      = jobStatus?.done    ?? 0
  const skipped   = jobStatus?.skipped ?? 0
  const errors    = jobStatus?.errors  ?? 0
  const processed = done + skipped + errors
  const progress  = Math.round((processed / Math.max(total, 1)) * 100)
  const isDone     = jobStatus?.status === 'done'
  const isError    = jobStatus?.status === 'error'
  const isStopped  = jobStatus?.status === 'stopped'
  const isStopping = !!(jobStatus?.stopping && !isStopped)
  const isRunning  = !isDone && !isError && !isStopped

  const runningResult = (jobStatus?.results ?? []).find(r => r.status === 'running')
  const allResults    = jobStatus?.results ?? []
  const errorResults  = allResults.filter(r => r.status === 'error')

  const handleStop = async () => {
    if (!jobId) return
    await stopIndexing(jobId)
    onStop?.()
  }

  const statusColor = isDone ? 'text-emerald-400' : isError ? 'text-red-400' : isStopped ? 'text-amber-400' : 'text-[#85adff]'
  const statusLabel = isDone ? '인덱싱 완료' : isError ? '오류 발생' : isStopped ? '중단됨' : isStopping ? '중단 중...' : '인덱싱 중...'
  const borderGlow  = isDone
    ? 'border-emerald-500/30 shadow-[0_0_60px_rgba(52,211,153,0.15)]'
    : isError ? 'border-red-500/30 shadow-[0_0_60px_rgba(248,113,113,0.15)]'
    : isStopped ? 'border-amber-500/30 shadow-[0_0_60px_rgba(251,191,36,0.15)]'
    : 'border-[#85adff]/20 shadow-[0_0_80px_rgba(133,173,255,0.2)]'

  const STEPS = ['프레임 캡셔닝', '음성 변환', '임베딩 생성', '벡터DB 저장']
  const STEP_ICONS = ['frame_inspect', 'mic', 'hub', 'database']

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg" onClick={onClose} />

      {/* card — 크게, 두 컬럼 */}
      <div className={`relative w-full max-w-2xl rounded-3xl overflow-hidden
        bg-[#080e22]/95 border backdrop-blur-2xl ${borderGlow} flex flex-col`}
        style={{ maxHeight: '90vh' }}>

        {/* ── 헤더 ── */}
        <div className="flex items-center justify-between px-7 pt-6 pb-4 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-3">
            {isRunning
              ? <span className="material-symbols-outlined text-[#85adff] text-2xl animate-spin">progress_activity</span>
              : isDone
                ? <span className="material-symbols-outlined text-emerald-400 text-2xl" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>
                : isError
                  ? <span className="material-symbols-outlined text-red-400 text-2xl" style={{ fontVariationSettings: '"FILL" 1' }}>error</span>
                  : <span className="material-symbols-outlined text-amber-400 text-2xl" style={{ fontVariationSettings: '"FILL" 1' }}>stop_circle</span>
            }
            <h2 className={`text-xl font-black tracking-tight ${statusColor}`}>{statusLabel}</h2>
            {rootPath && (
              <span className="text-xs text-on-surface-variant/40 font-mono truncate max-w-[200px]">
                {rootPath.split('\\').pop() || rootPath}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {isRunning && (
              <button onClick={handleStop} disabled={isStopping}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 text-xs font-bold transition-all disabled:opacity-40">
                <span className="material-symbols-outlined text-sm">stop</span>
                {isStopping ? '중단 중...' : '중단'}
              </button>
            )}
            <button onClick={onClose}
              className="w-8 h-8 rounded-full bg-white/8 hover:bg-white/15 flex items-center justify-center text-on-surface-variant hover:text-on-surface transition-all">
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>
        </div>

        {/* ── 본문: 두 컬럼 ── */}
        <div className="flex gap-0 flex-1 min-h-0 overflow-hidden">

          {/* 왼쪽: 원형 프로그레스 + 현재 파일 */}
          <div className="w-64 shrink-0 flex flex-col items-center justify-start pt-8 pb-6 px-6 border-r border-white/5 gap-6">

            {/* 원형 링 + 숫자 */}
            <div className="relative flex items-center justify-center">
              <RingProgress pct={progress} isDone={isDone} isError={isError} isStopped={isStopped} />
              <div className="absolute flex flex-col items-center">
                <span className={`text-4xl font-black tabular-nums leading-none ${statusColor}`}>{progress}</span>
                <span className="text-xs text-on-surface-variant/50 mt-1">%</span>
              </div>
            </div>

            {/* 전체 바 */}
            <div className="w-full space-y-2">
              <div className="h-2 bg-white/6 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-500 ${
                  isDone ? 'bg-emerald-500' : isError ? 'bg-red-500' : isStopped ? 'bg-amber-500'
                  : 'bg-gradient-to-r from-[#85adff] to-[#ac8aff]'
                }`} style={{ width: `${progress}%` }} />
              </div>
              <p className="text-[11px] text-center text-on-surface-variant/50 tabular-nums">
                {processed} / {total} 파일
              </p>
            </div>

            {/* 통계 */}
            <div className="w-full grid grid-cols-3 gap-2">
              {[
                { label: '완료', val: done,    color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
                { label: '건너뜀', val: skipped, color: 'text-amber-400',   bg: 'bg-amber-500/10'  },
                { label: '오류',  val: errors,  color: 'text-red-400',     bg: 'bg-red-500/10'    },
              ].map(s => (
                <div key={s.label} className={`${s.bg} rounded-xl p-2 flex flex-col items-center`}>
                  <span className={`text-xl font-black ${s.color} tabular-nums`}>{s.val}</span>
                  <span className="text-[9px] text-on-surface-variant/40 mt-0.5">{s.label}</span>
                </div>
              ))}
            </div>

            {/* 현재 처리 중 파일명 */}
            {runningResult && (
              <div className="w-full bg-[#85adff]/5 border border-[#85adff]/15 rounded-xl p-3">
                <p className="text-[9px] text-[#85adff]/60 uppercase tracking-widest font-bold mb-1">현재 처리 중</p>
                <p className="text-xs font-semibold text-[#dfe4fe] truncate">
                  {runningResult.path.split('\\').pop() || runningResult.path.split('/').pop()}
                </p>
              </div>
            )}
          </div>

          {/* 오른쪽: 동영상 스텝 + 파일 목록 */}
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">

            {/* 동영상 4단계 스텝 (동영상 처리 중일 때만) */}
            {isRunning && runningResult?.step != null && (
              <div className="shrink-0 px-6 pt-6 pb-5 border-b border-white/5">
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/40 mb-4">동영상 처리 단계</p>
                <div className="grid grid-cols-4 gap-3">
                  {STEPS.map((label, idx) => {
                    const sn       = idx + 1
                    const cur      = runningResult.step
                    const isPast   = sn < cur
                    const isActive = sn === cur
                    return (
                      <div key={label}
                        className={`relative flex flex-col items-center gap-2 p-3 rounded-2xl border transition-all duration-300 ${
                          isActive
                            ? 'bg-[#85adff]/10 border-[#85adff]/40 shadow-[0_0_20px_rgba(133,173,255,0.2)]'
                            : isPast
                              ? 'bg-emerald-500/8 border-emerald-500/20'
                              : 'bg-white/3 border-white/5'
                        }`}>
                        {/* 번호 / 아이콘 */}
                        <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-black border-2 transition-all ${
                          isActive
                            ? 'bg-[#85adff] border-[#85adff] text-[#070d1f] scale-110'
                            : isPast
                              ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
                              : 'bg-white/5 border-white/10 text-on-surface-variant/30'
                        }`}>
                          {isPast
                            ? <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>check</span>
                            : isActive
                              ? <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>
                              : <span className="text-xs">{sn}</span>
                          }
                        </div>
                        <span className={`text-[10px] font-bold text-center leading-tight ${
                          isActive ? 'text-[#85adff]' : isPast ? 'text-emerald-400' : 'text-on-surface-variant/25'
                        }`}>{label}</span>
                        {/* 활성 펄스 */}
                        {isActive && (
                          <div className="absolute inset-0 rounded-2xl border-2 border-[#85adff]/30 animate-ping opacity-50" />
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* 파일 전체 목록 */}
            <div className="flex-1 overflow-y-auto min-h-0">
              <div className="px-4 pt-4 pb-2 sticky top-0 bg-[#080e22]/95 backdrop-blur-sm z-10 border-b border-white/5">
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/40">파일 목록</p>
              </div>
              <div className="divide-y divide-white/4 px-2 pb-4">
                {allResults.map((r, i) => {
                  const fname = r.path.split('\\').pop() || r.path.split('/').pop()
                  const ext   = fname.split('.').pop()?.toLowerCase()
                  const ftype = r.file_type ?? (['mp4','avi','mov','mkv','wmv'].includes(ext) ? 'video'
                    : ['pdf','docx','txt'].includes(ext) ? 'doc'
                    : ['jpg','jpeg','png','gif','webp'].includes(ext) ? 'image'
                    : ['mp3','wav','flac','m4a'].includes(ext) ? 'audio' : null)
                  const icon  = TYPE_ICON[ftype] ?? 'insert_drive_file'
                  const color = TYPE_COLOR[ftype] ?? 'text-on-surface-variant'
                  const isCurrently = r.status === 'running'

                  return (
                    <div key={i}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-xl mx-1 my-0.5 transition-all duration-300 ${
                        isCurrently ? 'bg-[#85adff]/8 border border-[#85adff]/20' : 'border border-transparent hover:bg-white/3'
                      }`}>
                      <span className={`material-symbols-outlined text-base shrink-0 ${color}`}>{icon}</span>
                      <div className="flex-1 min-w-0">
                        <p className={`text-xs font-semibold truncate ${isCurrently ? 'text-[#dfe4fe]' : 'text-on-surface/70'}`}>{fname}</p>
                        {isCurrently && r.step_detail && (
                          <p className="text-[10px] text-[#85adff]/70 mt-0.5">[{r.step}/{r.step_total ?? 4}] {r.step_detail}</p>
                        )}
                        {r.status === 'error' && r.reason && (
                          <p className="text-[10px] text-red-400/70 mt-0.5 truncate">{r.reason}</p>
                        )}
                      </div>
                      {/* 상태 아이콘 */}
                      <div className="shrink-0">
                        {r.status === 'done'    && <span className="material-symbols-outlined text-emerald-400 text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>}
                        {r.status === 'running' && <span className="material-symbols-outlined text-[#85adff] text-lg animate-spin">progress_activity</span>}
                        {r.status === 'error'   && <span className="material-symbols-outlined text-red-400 text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>error</span>}
                        {r.status === 'skipped' && <span className="material-symbols-outlined text-amber-400/60 text-lg">skip_next</span>}
                        {r.status === 'pending' && <span className="material-symbols-outlined text-on-surface-variant/20 text-lg">radio_button_unchecked</span>}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── 데이터 소스 탭 ──────────────────────────────────────
function DataSourcesTab() {
  const [files, setFiles]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [confirming, setConfirming] = useState(null)   // 삭제 확인 중인 file_path
  const [deleting, setDeleting]     = useState(new Set()) // 삭제 요청 중인 file_path Set

  const loadFiles = () => {
    setLoading(true)
    fetch(`${API}/api/files/indexed`)
      .then(r => r.json())
      .then(d => { setFiles(d.files ?? []); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { loadFiles() }, [])

  const handleDeleteClick = (filePath) => {
    setConfirming(filePath)
  }

  const handleDeleteConfirm = async (filePath) => {
    setConfirming(null)
    setDeleting(prev => new Set(prev).add(filePath))
    try {
      const res = await fetch(`${API}/api/files/delete`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: filePath }),
      })
      if (!res.ok) throw new Error('삭제 실패')
      // 목록에서 즉시 제거
      setFiles(prev => prev.filter(f => f.file_path !== filePath))
    } catch (e) {
      setError(e.message)
    } finally {
      setDeleting(prev => { const s = new Set(prev); s.delete(filePath); return s })
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center py-32 gap-2">
      <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
      <span className="text-sm text-on-surface-variant">불러오는 중...</span>
    </div>
  )
  if (error) return <p className="text-red-400 text-sm p-8">{error}</p>
  if (files.length === 0) return (
    <div className="flex flex-col items-center gap-3 py-24">
      <span className="material-symbols-outlined text-on-surface-variant/20 text-5xl">database</span>
      <p className="text-sm text-on-surface-variant/40">아직 인덱싱된 파일이 없습니다.</p>
    </div>
  )

  // 타입별 그룹
  const byType = {}
  for (const f of files) {
    if (!byType[f.file_type]) byType[f.file_type] = []
    byType[f.file_type].push(f)
  }

  return (
    <div className="space-y-6">
      {/* 요약 카드 */}
      <div className="grid grid-cols-4 gap-4">
        {['doc','video','image','audio'].map(t => {
          const list = byType[t] ?? []
          const icon  = TYPE_ICON[t]  ?? 'insert_drive_file'
          const label = TYPE_LABEL[t] ?? t
          const color = TYPE_COLOR[t] ?? 'text-on-surface-variant'
          return (
            <div key={t} className="glass-panel rounded-xl p-4 border border-outline-variant/10">
              <div className="flex items-center gap-2 mb-3">
                <span className={`material-symbols-outlined text-base ${color}`}>{icon}</span>
                <span className="text-xs font-bold text-on-surface-variant uppercase tracking-widest">{label}</span>
              </div>
              <p className="text-2xl font-black text-on-surface">{list.length}<span className="text-xs font-normal text-on-surface-variant ml-1">개</span></p>
              <p className="text-[10px] text-on-surface-variant/40 mt-1">
                {list.reduce((s, f) => s + (f.chunk_count || 0), 0)} 청크
              </p>
            </div>
          )
        })}
      </div>

      {/* 파일 목록 */}
      <div className="glass-panel rounded-xl border border-outline-variant/10 overflow-hidden">
        <div className="px-4 py-3 border-b border-outline-variant/10 flex items-center justify-between">
          <h3 className="text-sm font-bold text-on-surface">전체 파일 <span className="text-on-surface-variant font-normal">({files.length})</span></h3>
          <button
            onClick={loadFiles}
            className="flex items-center gap-1 text-[10px] text-on-surface-variant/50 hover:text-primary transition-colors"
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            새로고침
          </button>
        </div>
        <div className="divide-y divide-outline-variant/8 max-h-[calc(100vh-340px)] overflow-y-auto">
          {files.map((f, i) => {
            const icon    = TYPE_ICON[f.file_type]  ?? 'insert_drive_file'
            const color   = TYPE_COLOR[f.file_type] ?? 'text-on-surface-variant'
            const sizeKB  = f.size != null ? (f.size / 1024).toFixed(1) + ' KB' : '-'
            const isConfirming = confirming === f.file_path
            const isDeleting   = deleting.has(f.file_path)

            return (
              <div
                key={i}
                className={`flex items-center gap-3 px-4 py-3 transition-colors group
                  ${isConfirming ? 'bg-red-500/8' : 'hover:bg-white/3'}
                  ${!f.exists ? 'opacity-40' : ''}`}
              >
                <span className={`material-symbols-outlined text-base shrink-0 ${color}`}>{icon}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-on-surface truncate">{f.file_name}</p>
                  <p className="text-[10px] text-on-surface-variant/40 font-mono truncate">{f.file_path}</p>
                </div>

                <span className="text-[10px] text-on-surface-variant/30 shrink-0">{sizeKB}</span>
                <span className="text-[10px] text-primary/60 shrink-0">{f.chunk_count} 청크</span>
                {!f.exists && (
                  <span className="material-symbols-outlined text-red-400 text-sm shrink-0" title="파일 없음">
                    error
                  </span>
                )}

                {/* 삭제 버튼 영역 */}
                {isDeleting ? (
                  <span className="material-symbols-outlined text-on-surface-variant/30 text-base animate-spin shrink-0">
                    progress_activity
                  </span>
                ) : isConfirming ? (
                  /* 인라인 확인 */
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className="text-[10px] text-red-400/80 font-bold">삭제?</span>
                    <button
                      onClick={() => handleDeleteConfirm(f.file_path)}
                      className="px-2 py-0.5 rounded-full bg-red-500 hover:bg-red-600 text-white text-[10px] font-bold transition-colors"
                    >
                      확인
                    </button>
                    <button
                      onClick={() => setConfirming(null)}
                      className="px-2 py-0.5 rounded-full bg-white/10 hover:bg-white/20 text-on-surface-variant text-[10px] font-bold transition-colors"
                    >
                      취소
                    </button>
                  </div>
                ) : (
                  /* 기본 상태: hover 시 휴지통 아이콘 */
                  <button
                    onClick={() => handleDeleteClick(f.file_path)}
                    title="인덱스에서 삭제"
                    className="opacity-0 group-hover:opacity-100 shrink-0 w-7 h-7 rounded-full hover:bg-red-500/15 flex items-center justify-center text-on-surface-variant/40 hover:text-red-400 transition-all"
                  >
                    <span className="material-symbols-outlined text-base">delete</span>
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── 벡터 저장소 탭 ──────────────────────────────────────
function VectorStoreTab() {
  const [stats, setStats]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')

  useEffect(() => {
    fetch(`${API}/api/files/stats`)
      .then(r => r.json())
      .then(d => { setStats(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center py-32 gap-2">
      <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
      <span className="text-sm text-on-surface-variant">불러오는 중...</span>
    </div>
  )
  if (error) return <p className="text-red-400 text-sm p-8">{error}</p>

  const byType = stats?.by_type ?? {}

  return (
    <div className="space-y-6">
      {/* 총합 */}
      <div className="glass-panel rounded-xl p-6 border border-primary/20 bg-primary/5">
        <p className="text-[10px] font-bold uppercase tracking-widest text-primary mb-2">총 벡터 데이터</p>
        <div className="flex items-end gap-6">
          <div>
            <p className="text-4xl font-black text-on-surface">{stats?.total_chunks?.toLocaleString()}</p>
            <p className="text-xs text-on-surface-variant mt-1">총 청크 (벡터)</p>
          </div>
          <div>
            <p className="text-2xl font-black text-on-surface">{stats?.total_files}</p>
            <p className="text-xs text-on-surface-variant mt-1">총 파일</p>
          </div>
        </div>
      </div>

      {/* 타입별 컬렉션 */}
      <div className="grid grid-cols-2 gap-4">
        {[
          { key: 'video', db: 'embedded_DB/Movie', dim: '1024d', model: 'e5-large', col: 'files_video' },
          { key: 'doc',   db: 'embedded_DB/Doc',   dim: '384d',  model: 'MiniLM',   col: 'files_doc'   },
          { key: 'image', db: 'embedded_DB/Img',   dim: '384d',  model: 'MiniLM',   col: 'files_image' },
          { key: 'audio', db: 'embedded_DB/Rec',   dim: '768d',  model: 'ko-sroberta', col: 'files_audio' },
        ].map(({ key, db, dim, model, col }) => {
          const t     = byType[key] ?? { file_count: 0, chunk_count: 0 }
          const icon  = TYPE_ICON[key]  ?? 'insert_drive_file'
          const label = TYPE_LABEL[key] ?? key
          const color = TYPE_COLOR[key] ?? 'text-on-surface-variant'
          return (
            <div key={key} className="glass-panel rounded-xl p-5 border border-outline-variant/10 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`material-symbols-outlined ${color}`}>{icon}</span>
                  <span className="font-bold text-on-surface">{label}</span>
                </div>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${color} bg-white/5 border-white/10`}>{dim}</span>
              </div>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">파일 수</span>
                  <span className="font-bold text-on-surface">{t.file_count}개</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">청크 수</span>
                  <span className="font-bold text-on-surface">{t.chunk_count?.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">임베딩 모델</span>
                  <span className="font-mono text-on-surface-variant/60">{model}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">컬렉션</span>
                  <span className="font-mono text-on-surface-variant/60">{col}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">경로</span>
                  <span className="font-mono text-on-surface-variant/50 text-[10px]">{db}</span>
                </div>
              </div>
              {/* 채움 비율 바 */}
              <div className="h-1 bg-white/8 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${t.chunk_count > 0 ? 'bg-gradient-to-r from-primary to-secondary' : 'bg-transparent'}`}
                  style={{ width: `${Math.min(100, (t.chunk_count / Math.max(stats?.total_chunks, 1)) * 100)}%` }} />
              </div>
            </div>
          )
        })}
      </div>

      {/* ChromaDB 정보 */}
      <div className="glass-panel rounded-xl p-5 border border-outline-variant/10">
        <p className="text-[10px] font-bold uppercase tracking-widest text-secondary mb-3">ChromaDB 정보</p>
        <div className="grid grid-cols-3 gap-4 text-xs">
          {[
            ['엔진', 'ChromaDB (PersistentClient)'],
            ['유사도 메트릭', 'Cosine Similarity'],
            ['인덱스', 'HNSW'],
          ].map(([k, v]) => (
            <div key={k} className="space-y-1">
              <p className="text-on-surface-variant">{k}</p>
              <p className="font-bold text-on-surface">{v}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── 메인 ────────────────────────────────────────────────
export default function DataIndexing() {
  const navigate = useNavigate()

  const [tab, setTab] = useState('indexing') // 'sources' | 'indexing' | 'store'

  const [rootPath, setRootPath] = useState('')
  const [rootItems, setRootItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')

  const [checkedPaths, setCheckedPaths] = useState(new Set())

  const [indexing, setIndexing] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [jobError, setJobError] = useState('')
  const [modalVisible, setModalVisible] = useState(false)
  const pollRef = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const handleSelectFolder = async () => {
    const path = await window.electronAPI?.selectFolder()
    if (!path) return

    setRootPath(path)
    setLoadError('')
    setLoading(true)
    setRootItems([])
    setCheckedPaths(new Set())
    stopPolling()
    setJobStatus(null)
    setJobError('')
    setIndexing(false)

    try {
      const items = await scanPath(path)
      setRootItems(items)
      // 지원 파일 기본 체크
      const supported = items.filter(i => i.kind === 'file' && i.type).map(i => i.path)
      setCheckedPaths(new Set(supported))
    } catch (e) {
      setLoadError(`스캔 실패: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const toggleFile = useCallback((path) => {
    setCheckedPaths(prev => {
      const next = new Set(prev)
      next.has(path) ? next.delete(path) : next.add(path)
      return next
    })
  }, [])

  // 폴더 체크박스 → 여러 파일 일괄 설정
  const setManyFiles = useCallback((paths, checked) => {
    setCheckedPaths(prev => {
      const next = new Set(prev)
      paths.forEach(p => checked ? next.add(p) : next.delete(p))
      return next
    })
  }, [])

  const handleStartIndexing = async () => {
    if (checkedPaths.size === 0) return
    setIndexing(true)
    setJobError('')
    setJobStatus(null)
    setModalVisible(true)
    try {
      const { job_id } = await startIndexing([...checkedPaths])
      setJobId(job_id)
      const initial = await fetchStatus(job_id)
      setJobStatus(initial)
      pollRef.current = setInterval(async () => {
        try {
          const s = await fetchStatus(job_id)
          setJobStatus(s)
          if (s.status === 'done' || s.status === 'error' || s.status === 'stopped') {
            stopPolling(); setIndexing(false)
          }
        } catch { stopPolling(); setIndexing(false); setJobError('상태 조회 실패') }
      }, 1000)
    } catch { setJobError('인덱싱 시작 실패'); setIndexing(false); setModalVisible(false) }
  }

  const jobResultMap = jobStatus?.results
    ? Object.fromEntries(jobStatus.results.map(r => [r.path, r]))
    : null

  const selectedCount = checkedPaths.size

  return (
    <div className="bg-surface text-on-surface flex h-screen overflow-hidden">

      {/* Sidebar */}
      <aside className="w-64 shrink-0 h-screen bg-[#070d1f]/60 backdrop-blur-xl flex flex-col pt-12 pb-4 border-r border-[#41475b]/15 shadow-[20px_0_40px_rgba(133,173,255,0.05)] z-50">
        <div className="px-4 mb-8 flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-primary to-secondary rounded-lg flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-on-primary-fixed text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>dataset</span>
          </div>
          <div>
            <h1 className="text-xl font-black text-[#dfe4fe] leading-none">DB_insight</h1>
            <p className="text-[0.65rem] uppercase tracking-widest text-[#a5aac2] mt-1">데이터 인덱싱</p>
          </div>
        </div>

        <nav className="flex-1 px-3 space-y-1">
          {[
            { icon: 'database',      label: '워크스페이스', onClick: () => navigate('/search') },
            { icon: 'hub',           label: '데이터 소스',  tab: 'sources'  },
            { icon: 'account_tree',  label: '인덱싱',       tab: 'indexing' },
            { icon: 'memory',        label: '벡터 저장소',  tab: 'store'    },
          ].map(item => (
            <button
              key={item.label}
              onClick={item.onClick ?? (() => setTab(item.tab))}
              className={`w-full flex items-center gap-3 rounded-xl px-4 py-2.5 text-[0.75rem] font-manrope uppercase tracking-widest transition-all
                ${item.tab === tab
                  ? 'text-primary bg-[#1c253e]'
                  : 'text-[#a5aac2] hover:bg-[#1c253e]/50 hover:text-[#dfe4fe]'}`}
            >
              <span className="material-symbols-outlined text-base">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        {selectedCount > 0 && (
          <div className="mx-3 mb-3 p-3 rounded-xl bg-primary/10 border border-primary/20">
            <p className="text-[10px] text-primary font-bold uppercase tracking-widest mb-1">선택됨</p>
            <p className="text-xl font-black text-primary leading-none">{selectedCount}<span className="text-xs ml-1 font-normal">개 파일</span></p>
          </div>
        )}

        <div className="px-4 mt-auto pt-4 border-t border-outline-variant/10 flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-primary">account_circle</span>
          </div>
          <div className="overflow-hidden">
            <p className="text-sm font-bold text-on-surface truncate">관리자</p>
            <button onClick={() => navigate('/settings')} className="text-[0.65rem] text-on-surface-variant hover:text-primary transition-colors">
              설정 →
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden bg-surface-dim relative">
        <div className="absolute top-0 right-0 w-96 h-96 bg-primary/10 rounded-full blur-[120px] pointer-events-none" />

        {/* 드래그 타이틀바 */}
        <header
          className="shrink-0 bg-[#070d1f] flex justify-end items-center px-2 h-8 z-40"
          style={{ WebkitAppRegion: 'drag' }}
        >
          <div style={{ WebkitAppRegion: 'no-drag' }}>
            <WindowControls />
          </div>
        </header>

        <div className="flex-1 flex flex-col gap-4 p-5 overflow-hidden">

          {/* 탭: 데이터 소스 */}
          {tab === 'sources' && (
            <div className="flex-1 overflow-y-auto min-h-0">
              <h2 className="text-lg font-black text-on-surface mb-4">데이터 소스</h2>
              <DataSourcesTab />
            </div>
          )}

          {/* 탭: 벡터 저장소 */}
          {tab === 'store' && (
            <div className="flex-1 overflow-y-auto min-h-0">
              <h2 className="text-lg font-black text-on-surface mb-4">벡터 저장소</h2>
              <VectorStoreTab />
            </div>
          )}

          {/* 탭: 인덱싱 (기존 UI) */}
          {tab === 'indexing' && <>

          {/* 폴더 선택 바 */}
          <div className="shrink-0 glass-panel px-4 py-2.5 rounded-xl border border-outline-variant/15 flex items-center gap-3">
            <button
              onClick={handleSelectFolder}
              disabled={loading || indexing}
              className="shrink-0 px-4 py-2 rounded-full bg-surface-container-high border border-outline-variant/40 hover:bg-surface-container-highest transition-all text-sm font-semibold flex items-center gap-2 disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-base">folder_shared</span>
              {loading ? '스캔 중...' : '폴더 선택'}
            </button>
            <span className="text-sm font-mono text-on-surface-variant/50 flex-1 truncate">
              {rootPath || '폴더를 선택하세요'}
            </span>
            {rootItems.length > 0 && (
              <span className="shrink-0 px-2.5 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-bold">
                {rootItems.length}개
              </span>
            )}
          </div>

          {/* 파일 트리 */}
          <div className="flex-1 glass-panel rounded-xl border border-outline-variant/15 overflow-hidden flex flex-col min-h-0">
            <div className="shrink-0 px-4 py-2.5 border-b border-outline-variant/10 flex items-center justify-between">
              <h2 className="text-base font-bold tracking-tight text-on-surface">리소스 탐색기</h2>
              {jobStatus && (
                <button
                  onClick={() => setModalVisible(true)}
                  className={`flex items-center gap-1.5 text-xs font-bold uppercase px-2.5 py-0.5 rounded-full transition-all hover:brightness-125
                    ${jobStatus.status === 'done' ? 'bg-emerald-500/15 text-emerald-400'
                    : jobStatus.status === 'error' ? 'bg-red-500/15 text-red-400'
                    : 'bg-primary/10 text-primary'}`}
                >
                  {jobStatus.status === 'running' && <span className="material-symbols-outlined text-xs animate-spin">progress_activity</span>}
                  {jobStatus.status === 'done' ? '완료' : jobStatus.status === 'error' ? '오류' : '처리 중'}
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto py-1.5 min-h-0">
              {loading && (
                <div className="flex items-center justify-center gap-2 py-12">
                  <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
                  <span className="text-sm text-on-surface-variant">스캔 중...</span>
                </div>
              )}
              {!loading && loadError && (
                <div className="flex flex-col items-center gap-2 py-12">
                  <span className="material-symbols-outlined text-red-400 text-3xl">wifi_off</span>
                  <p className="text-sm text-red-400">{loadError}</p>
                  <p className="text-xs text-on-surface-variant/40">Flask 백엔드가 실행 중인지 확인하세요</p>
                </div>
              )}
              {!loading && !loadError && rootItems.length === 0 && (
                <div className="flex flex-col items-center gap-3 py-16">
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-5xl">folder_open</span>
                  <p className="text-sm text-on-surface-variant/30">
                    {rootPath ? '이 폴더는 비어 있습니다.' : '폴더를 선택하면 파일 목록이 표시됩니다.'}
                  </p>
                </div>
              )}

              {/* 트리 */}
              {!loading && !loadError && rootItems.map(item =>
                item.kind === 'folder'
                  ? <FolderRow
                      key={item.path} item={item} depth={0}
                      checkedPaths={checkedPaths}
                      onToggle={toggleFile}
                      onSetMany={setManyFiles}
                      jobResultMap={jobResultMap}
                    />
                  : <FileRow
                      key={item.path} item={item} depth={0}
                      checked={checkedPaths.has(item.path)}
                      onToggle={toggleFile}
                      jobResult={jobResultMap?.[item.path]}
                    />
              )}
            </div>
          </div>

          {/* 인덱싱 버튼 */}
          <div className="shrink-0 flex flex-col items-center gap-2 pb-1">
            {jobError && <p className="text-sm text-red-400">{jobError}</p>}
            <button
              onClick={handleStartIndexing}
              disabled={selectedCount === 0 || indexing}
              className="relative group disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <div className="absolute -inset-0.5 bg-gradient-to-r from-primary to-secondary rounded-full blur opacity-40 group-hover:opacity-70 transition duration-500" />
              <div className="relative px-10 py-3.5 bg-[#000000] rounded-full flex items-center divide-x divide-outline-variant/30">
                <span className="flex items-center gap-2.5 pr-5">
                  <span
                    className={`material-symbols-outlined text-primary ${indexing ? 'animate-spin' : 'animate-pulse'}`}
                    style={{ fontVariationSettings: '"FILL" 1' }}
                  >{indexing ? 'progress_activity' : 'rocket_launch'}</span>
                  <span className="text-on-surface font-black tracking-widest text-sm uppercase">
                    {indexing ? '인덱싱 중...' : '인덱싱 시작'}
                  </span>
                </span>
                <span className="pl-5 text-secondary text-xs font-bold uppercase tracking-widest">
                  {selectedCount > 0 ? `${selectedCount}개 선택됨` : '파일 미선택'}
                </span>
              </div>
            </button>
          </div>

          </> /* end tab === 'indexing' */}
        </div>
      </main>

      {/* 인덱싱 진행 모달 */}
      {modalVisible && (
        <IndexingModal
          rootPath={rootPath}
          selectedCount={selectedCount}
          jobStatus={jobStatus}
          jobId={jobId}
          onClose={() => setModalVisible(false)}
          onStop={() => { stopPolling(); setIndexing(false) }}
        />
      )}
    </div>
  )
}
