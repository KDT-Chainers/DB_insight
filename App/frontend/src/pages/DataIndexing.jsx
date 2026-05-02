import { useNavigate } from 'react-router-dom'
import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import WindowControls from '../components/WindowControls'
import PageSidebar from '../components/PageSidebar'
import { API_BASE as API } from '../api'
import { checkIndexed, fetchOrphans } from '../api/registry'
import IndexedBadge from '../components/indexing/IndexedBadge'
import SelectNewOnlyButton from '../components/indexing/SelectNewOnlyButton'
import FolderStatusBadge from '../components/indexing/FolderStatusBadge'
import IndexingETA from '../components/indexing/IndexingETA'
import { saveIndexingState, loadIndexingState,
         saveActiveJob, loadActiveJob, clearActiveJob } from '../utils/indexingPersist'
import { estimateIndexing } from '../api/indexing'
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

// 폴더 이하 모든 지원 파일 경로를 재귀적으로 수집한다.
// 폴더 체크박스 클릭 시 하위 트리 전체를 한 번에 선택/해제하기 위한 헬퍼.
// 형제 폴더는 병렬 fetch, 깊이 방향은 순차. 백엔드 스캔이 1단계만 반환하므로
// 다단계 raw_DB(예: Rec/태윤_1차/...)에서도 파일까지 모두 모은다.
async function collectAllFilesRecursive(folderPath) {
  try {
    const items = await scanPath(folderPath)
    const direct = items
      .filter(i => i.kind === 'file' && i.type)
      .map(i => i.path)
    const subFolders = items.filter(i => i.kind === 'folder').map(i => i.path)
    if (subFolders.length === 0) return direct
    const sub = await Promise.all(subFolders.map(p => collectAllFilesRecursive(p)))
    return [...direct, ...sub.flat()]
  } catch {
    return []
  }
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
function FileRow({ item, depth, checked, onToggle, jobResult, indexedInfo }) {
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
            <span className="text-sm text-primary/60 font-bold tabular-nums">{step}/{total}</span>
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
      <span className="text-base text-on-surface flex-1 truncate">{item.name}</span>
      <IndexedBadge indexed={indexedInfo?.indexed} domain={indexedInfo?.domain} />
      <span className="text-sm text-on-surface-variant/30 shrink-0 group-hover:text-on-surface-variant/60">{sizeKB} KB</span>
      {statusIcon}
    </div>
  )
}

// ── 폴더 행 (lazy expand + 체크박스) ────────────────────
function FolderRow({ item, depth, checkedPaths, onToggle, onSetMany, jobResultMap, indexedMap, registerPaths, orphanMap, registerOrphans }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [checkLoading, setCheckLoading] = useState(false)
  const [children, setChildren] = useState(null) // null = 아직 로드 안 함
  const checkboxRef = useRef(null)

  // 직접 파일 자식 목록 (loaded 시)
  const directFiles = (children ?? []).filter(i => i.kind === 'file' && i.type)

  // 재귀 트리(하위 모든 파일) 기준 체크 상태 — indexedMap 에 등재된 파일 중
  // 이 폴더 경로 prefix 인 것들. registerPaths 가 채워주므로 폴더 클릭 직후
  // 즉시 반영된다. raw_DB 같이 1단계 직접 파일이 0개인 폴더에서도 동작.
  const subtreeFiles = useMemo(() => {
    if (!indexedMap) return []
    const base = item.path
    const out = []
    for (const p of Object.keys(indexedMap)) {
      if (!p.startsWith(base)) continue
      const sep = p[base.length]
      if (sep === '\\' || sep === '/') out.push(p)
    }
    return out
  }, [indexedMap, item.path])

  // 표시용 카운트는 (1) 직접 파일 / (2) subtree 중 더 큰 쪽으로
  const effectiveFiles = subtreeFiles.length > directFiles.length
    ? subtreeFiles
    : directFiles.map(i => i.path)
  const checkedCount = effectiveFiles.filter(p => checkedPaths.has(p)).length
  const allChecked = effectiveFiles.length > 0 && checkedCount === effectiveFiles.length
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
        registerPaths?.(items.filter(i => i.kind === 'file' && i.type).map(i => i.path))
        registerOrphans?.(item.path)
      } catch {
        setChildren([])
      } finally {
        setLoading(false)
      }
    }
    setOpen(v => !v)
  }

  // 폴더 체크박스 클릭 — 하위 트리 전체(재귀)를 일괄 선택/해제
  const handleFolderCheck = async (e) => {
    e.stopPropagation()
    // 의도: 현재 전체 체크 또는 부분 체크면 → 모두 해제,
    //       그 외(미체크)면 → 하위 모든 파일 선택.
    const wantSelectAll = !(allChecked || someChecked)

    setCheckLoading(true)
    let allFiles = []
    try {
      // 1단계 스캔이 아직이면 펼치며 선로딩 (UX: 클릭 즉시 반응)
      if (children === null) {
        try {
          const items = await scanPath(item.path)
          setChildren(items)
          setOpen(true)
        } catch {
          setChildren([])
        }
      }
      // 핵심: 하위 트리 전체 재귀 수집
      allFiles = await collectAllFilesRecursive(item.path)
      if (allFiles.length > 0) registerPaths?.(allFiles)
      registerOrphans?.(item.path)
    } finally {
      setCheckLoading(false)
    }

    if (allFiles.length > 0) onSetMany(allFiles, wantSelectAll)
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
          <span className="text-base text-on-surface flex-1 truncate font-medium">{item.name}</span>
        </span>

        {/* 상태 배지 — 인덱싱 완료(초록) / 부분(파랑) / 신규(황색) / 삭제(빨강) */}
        <FolderStatusBadge
          subtreeFiles={subtreeFiles}
          indexedMap={indexedMap}
          childCount={children?.length ?? null}
          orphanCount={orphanMap?.[item.path] ?? 0}
        />
      </div>

      {/* 자식 목록 */}
      {open && children !== null && (
        <>
          {children.length === 0 && (
            <div
              className="py-1 text-base text-on-surface-variant/30 italic"
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
                  indexedMap={indexedMap}
                  registerPaths={registerPaths}
                  orphanMap={orphanMap}
                  registerOrphans={registerOrphans}
                />
              : <FileRow
                  key={child.path} item={child} depth={depth + 1}
                  checked={checkedPaths.has(child.path)}
                  onToggle={onToggle}
                  jobResult={jobResultMap?.[child.path]}
                  indexedInfo={indexedMap?.[child.path]}
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
function _fmtDuration(sec) {
  if (sec == null || !isFinite(sec) || sec < 0) return '—'
  if (sec < 1) return '< 1s'
  const total = Math.round(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

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

  // [ETA] 잔여 시간 추정 — 1초 tick 으로 갱신.
  // [BUGFIX] 모달 close/open 시 startTime 리셋 → ETA 가 모달 재진입 시점부터
  // 다시 계산되어 부풀려지는 문제. 백엔드 jobStatus.started_at (epoch sec) 사용
  // → 모달 상태와 무관하게 일관된 elapsed/rate.
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!isRunning) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [isRunning])

  let remainingSec = null
  if (isRunning && jobStatus?.started_at && processed > 0 && processed < total) {
    const elapsedSec = Date.now() / 1000 - jobStatus.started_at
    if (elapsedSec > 0.5) {
      const rate = processed / elapsedSec
      if (rate > 0) remainingSec = (total - processed) / rate
    }
  }

  const runningResult = (jobStatus?.results ?? []).find(r => r.status === 'running')
  const allResults    = jobStatus?.results ?? []
  const errorResults  = allResults.filter(r => r.status === 'error')

  const handleStop = async () => {
    if (!jobId) return
    await stopIndexing(jobId)
    onStop?.()
  }

  // 100% 인데 백엔드 status 가 아직 'done' 으로 전환 안 된 상태도 완료로 간주
  // (모든 파일 처리 끝 + running 상태 파일 없음 → 사실상 완료)
  const isProgressComplete = progress >= 100 && !runningResult && !isError && !isStopped && !isStopping
  const isEffectivelyDone  = isDone || isProgressComplete

  const statusColor = isEffectivelyDone ? 'text-emerald-400' : isError ? 'text-red-400' : isStopped ? 'text-amber-400' : 'text-[#85adff]'
  const statusLabel = isEffectivelyDone ? '인덱싱 완료' : isError ? '오류 발생' : isStopped ? '중단됨' : isStopping ? '중단 중...' : '인덱싱 중...'
  const borderGlow  = isEffectivelyDone
    ? 'border-emerald-500/30 shadow-[0_0_60px_rgba(52,211,153,0.15)]'
    : isError ? 'border-red-500/30 shadow-[0_0_60px_rgba(248,113,113,0.15)]'
    : isStopped ? 'border-amber-500/30 shadow-[0_0_60px_rgba(251,191,36,0.15)]'
    : 'border-[#85adff]/20 shadow-[0_0_80px_rgba(133,173,255,0.2)]'

  // 파일 확장자로 파일 타입 판별
  const _getFileType = (path) => {
    const ext = path.split('.').pop()?.toLowerCase() ?? ''
    if (['mp4','avi','mov','mkv','wmv','flv','webm'].includes(ext)) return 'video'
    if (['jpg','jpeg','png','webp','gif','bmp'].includes(ext)) return 'image'
    if (['pdf','docx','doc','pptx','ppt','xlsx','xls','txt','md','html','hwp'].includes(ext)) return 'doc'
    if (['mp3','wav','flac','m4a','aac','ogg','wma'].includes(ext)) return 'audio'
    return null
  }

  const runningFileType = runningResult ? _getFileType(runningResult.path) : null

  // 파일 타입별 파이프라인 정의
  const PIPELINE = {
    image: {
      label: '이미지 처리 단계 (TRI-CHEF)',
      steps: ['Qwen2-VL 캡션 생성', '3축 임베딩', '벡터DB 저장'],
      icons: ['photo_camera', 'hub', 'database'],
      color: 'emerald',
      cols: 'grid-cols-3',
    },
    doc: {
      label: '문서 처리 단계 (TRI-CHEF)',
      steps: ['페이지 렌더링', 'Qwen2-VL 캡션 생성', '3축 임베딩', '벡터DB 저장'],
      icons: ['picture_as_pdf', 'description', 'hub', 'database'],
      color: 'emerald',
      cols: 'grid-cols-4',
    },
    video: {
      label: '동영상 처리 단계 (TRI-CHEF)',
      steps: ['프레임 추출', 'SigLIP2 Re + DINOv2 Z', 'Whisper STT', 'BGE-M3 Im', '벡터DB 저장'],
      icons: ['movie_filter', 'visibility', 'mic', 'hub', 'database'],
      color: 'blue',
      cols: 'grid-cols-5',
    },
    audio: {
      label: '음성 처리 단계 (TRI-CHEF)',
      steps: ['오디오 표준화', 'Whisper STT', 'BGE-M3 Im + SigLIP2 Re', '벡터DB 저장'],
      icons: ['graphic_eq', 'mic', 'hub', 'database'],
      color: 'amber',
      cols: 'grid-cols-4',
    },
  }

  const pipeline   = PIPELINE[runningFileType] ?? PIPELINE.video
  const STEPS      = pipeline.steps
  const STEP_ICONS = pipeline.icons
  const isTriChefMode = runningFileType === 'image' || runningFileType === 'doc'

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
            {isEffectivelyDone
              ? <span className="material-symbols-outlined text-emerald-400 text-2xl" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>
              : isError
                ? <span className="material-symbols-outlined text-red-400 text-2xl" style={{ fontVariationSettings: '"FILL" 1' }}>error</span>
                : isStopped
                  ? <span className="material-symbols-outlined text-amber-400 text-2xl" style={{ fontVariationSettings: '"FILL" 1' }}>stop_circle</span>
                  : <span className="material-symbols-outlined text-[#85adff] text-2xl animate-spin">progress_activity</span>
            }
            <h2 className={`text-xl font-black tracking-tight ${statusColor}`}>{statusLabel}</h2>
            {rootPath && (
              <span className="text-xs text-on-surface-variant/40 font-mono truncate max-w-[200px]">
                {rootPath.split('\\').pop() || rootPath}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {isRunning && !isEffectivelyDone && (
              <button onClick={handleStop} disabled={isStopping}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 text-base font-bold transition-all disabled:opacity-40">
                <span className="material-symbols-outlined text-lg">stop</span>
                {isStopping ? '중단 중...' : '중단'}
              </button>
            )}
            <button onClick={onClose}
              className="w-8 h-8 rounded-full bg-white/8 hover:bg-white/15 flex items-center justify-center text-on-surface-variant hover:text-on-surface transition-all">
              <span className="material-symbols-outlined text-lg">close</span>
            </button>
          </div>
        </div>

        {/* ── 본문: 두 컬럼 ── */}
        <div className="flex gap-0 flex-1 min-h-0 overflow-hidden">

          {/* 왼쪽: 원형 프로그레스 + 현재 파일 */}
          <div className="w-64 shrink-0 flex flex-col items-center justify-start pt-8 pb-6 px-6 border-r border-white/5 gap-6">

            {/* 원형 링 + 숫자 */}
            <div className="relative flex items-center justify-center">
              <RingProgress pct={progress} isDone={isEffectivelyDone} isError={isError} isStopped={isStopped} />
              <div className="absolute flex flex-col items-center">
                <span className={`text-4xl font-black tabular-nums leading-none ${statusColor}`}>{progress}</span>
                <span className="text-xs text-on-surface-variant/50 mt-1">%</span>
              </div>
            </div>

            {/* 전체 바 */}
            <div className="w-full space-y-2">
              <div className="h-2 bg-white/6 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-500 ${
                  isEffectivelyDone ? 'bg-emerald-500' : isError ? 'bg-red-500' : isStopped ? 'bg-amber-500'
                  : 'bg-gradient-to-r from-[#85adff] to-[#ac8aff]'
                }`} style={{ width: `${progress}%` }} />
              </div>
              <p className="text-sm text-center text-on-surface-variant/50 tabular-nums">
                {processed} / {total} 파일
              </p>
              {/* [ETA] 잔여 시간 — 진행률 기반 실시간 추정 (1초 tick). 100% 도달 시 표시 안 함. */}
              {remainingSec != null && !isEffectivelyDone && (
                <p className="text-xs text-center text-on-surface-variant/60 tabular-nums">
                  <span className="text-on-surface-variant/40">잔여 약</span>{' '}
                  <span className="font-bold text-[#85adff]">{_fmtDuration(remainingSec)}</span>
                </p>
              )}
              {isEffectivelyDone && (
                <p className="text-xs text-center text-emerald-400/80 tabular-nums">
                  완료
                </p>
              )}
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
                  <span className="text-sm text-on-surface-variant/40 mt-0.5">{s.label}</span>
                </div>
              ))}
            </div>

            {/* 현재 처리 중 파일명 */}
            {runningResult && (
              <div className="w-full bg-[#85adff]/5 border border-[#85adff]/15 rounded-xl p-3">
                <p className="text-sm text-[#85adff]/60 uppercase tracking-widest font-bold mb-1">현재 처리 중</p>
                <p className="text-sm font-semibold text-[#dfe4fe] truncate">
                  {runningResult.path.split('\\').pop() || runningResult.path.split('/').pop()}
                </p>
              </div>
            )}
          </div>

          {/* 오른쪽: 동영상 스텝 + 파일 목록 */}
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">

            {/* 처리 단계 — 파일 타입별 4종 파이프라인 */}
            {isRunning && runningResult?.step != null && (() => {
              const clr = pipeline.color
              const chipColor       = clr === 'emerald' ? 'text-emerald-400' : clr === 'amber' ? 'text-amber-400' : 'text-[#85adff]'
              const chipActiveBg    = clr === 'emerald' ? 'bg-emerald-400 border-emerald-400' : clr === 'amber' ? 'bg-amber-400 border-amber-400' : 'bg-[#85adff] border-[#85adff]'
              const chipActiveShadow = clr === 'emerald'
                ? 'bg-emerald-500/8 border-emerald-500/30 shadow-[0_0_20px_rgba(52,211,153,0.2)]'
                : clr === 'amber'
                  ? 'bg-amber-500/8 border-amber-500/30 shadow-[0_0_20px_rgba(251,191,36,0.2)]'
                  : 'bg-[#85adff]/10 border-[#85adff]/40 shadow-[0_0_20px_rgba(133,173,255,0.2)]'
              const pingBorder      = clr === 'emerald' ? 'border-emerald-400/30' : clr === 'amber' ? 'border-amber-400/30' : 'border-[#85adff]/30'
              return (
                <div className="shrink-0 px-6 pt-6 pb-5 border-b border-white/5">
                  <p className="text-sm font-bold uppercase tracking-widest text-on-surface-variant/40 mb-4">
                    {pipeline.label}
                  </p>
                  <div className={`grid gap-3 ${pipeline.cols}`}>
                    {STEPS.map((label, idx) => {
                      const sn       = idx + 1
                      const cur      = runningResult.step
                      const isPast   = sn < cur
                      const isActive = sn === cur
                      return (
                        <div key={label}
                          className={`relative flex flex-col items-center gap-2 p-3 rounded-2xl border transition-all duration-300 ${
                            isActive
                              ? chipActiveShadow
                              : isPast
                                ? 'bg-emerald-500/8 border-emerald-500/20'
                                : 'bg-white/3 border-white/5'
                          }`}>
                          {/* 번호 / 아이콘 */}
                          <div className={`w-9 h-9 rounded-full flex items-center justify-center text-lg font-black border-2 transition-all ${
                            isActive
                              ? `${chipActiveBg} text-[#070d1f] scale-110`
                              : isPast
                                ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
                                : 'bg-white/5 border-white/10 text-on-surface-variant/30'
                          }`}>
                            {isPast
                              ? <span className="material-symbols-outlined text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>check</span>
                              : isActive
                                ? <span className="material-symbols-outlined text-lg animate-spin">progress_activity</span>
                                : <span className="material-symbols-outlined text-lg opacity-40">{STEP_ICONS[idx]}</span>
                            }
                          </div>
                          <span className={`text-sm font-bold text-center leading-tight ${
                            isActive ? chipColor : isPast ? 'text-emerald-400' : 'text-on-surface-variant/25'
                          }`}>{label}</span>
                          {/* 활성 펄스 */}
                          {isActive && (
                            <div className={`absolute inset-0 rounded-2xl border-2 ${pingBorder} animate-ping opacity-50`} />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })()}

            {/* 파일 전체 목록 */}
            <div className="flex-1 overflow-y-auto min-h-0">
              <div className="px-4 pt-4 pb-2 sticky top-0 bg-[#080e22]/95 backdrop-blur-sm z-10 border-b border-white/5">
                <p className="text-sm font-bold uppercase tracking-widest text-on-surface-variant/40">파일 목록</p>
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
                        <p className={`text-sm font-semibold truncate ${isCurrently ? 'text-[#dfe4fe]' : 'text-on-surface/70'}`}>{fname}</p>
                        {isCurrently && r.step_detail && (
                          <p className="text-sm text-[#85adff]/70 mt-0.5">[{r.step}/{r.step_total ?? pipeline.steps.length}] {r.step_detail}</p>
                        )}
                        {r.status === 'error' && r.reason && (
                          <p className="text-sm text-red-400/70 mt-0.5 truncate">{r.reason}</p>
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
      <span className="text-base text-on-surface-variant">불러오는 중...</span>
    </div>
  )
  if (error) return <p className="text-red-400 text-lg p-8">{error}</p>
  if (files.length === 0) return (
    <div className="flex flex-col items-center gap-3 py-24">
      <span className="material-symbols-outlined text-on-surface-variant/20 text-5xl">database</span>
      <p className="text-base text-on-surface-variant/40">아직 인덱싱된 파일이 없습니다.</p>
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
                <span className="text-sm font-bold text-on-surface-variant uppercase tracking-widest">{label}</span>
              </div>
              <p className="text-2xl font-black text-on-surface">{list.length}<span className="text-xs font-normal text-on-surface-variant ml-1">개</span></p>
              <p className="text-sm text-on-surface-variant/40 mt-1">
                {list.reduce((s, f) => s + (f.chunk_count || 0), 0)} 청크
              </p>
            </div>
          )
        })}
      </div>

      {/* 파일 목록 */}
      <div className="glass-panel rounded-xl border border-outline-variant/10 overflow-hidden">
        <div className="px-4 py-3 border-b border-outline-variant/10 flex items-center justify-between">
          <h3 className="text-base font-bold text-on-surface">전체 파일 <span className="text-on-surface-variant font-normal">({files.length})</span></h3>
          <button
            onClick={loadFiles}
            className="flex items-center gap-1 text-lg text-on-surface-variant/50 hover:text-primary transition-colors"
          >
            <span className="material-symbols-outlined text-lg">refresh</span>
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
                  <p className="text-base font-semibold text-on-surface truncate">{f.file_name}</p>
                  <p className="text-sm text-on-surface-variant/40 font-mono truncate">{f.file_path}</p>
                </div>

                <span className="text-sm text-on-surface-variant/30 shrink-0">{sizeKB}</span>
                <span className="text-sm text-primary/60 shrink-0">{f.chunk_count} 청크</span>
                {!f.exists && (
                  <span className="material-symbols-outlined text-red-400 text-lg shrink-0" title="파일 없음">
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
                    <span className="text-sm text-red-400/80 font-bold">삭제?</span>
                    <button
                      onClick={() => handleDeleteConfirm(f.file_path)}
                      className="px-2 py-0.5 rounded-full bg-red-500 hover:bg-red-600 text-white text-lg font-bold transition-colors"
                    >
                      확인
                    </button>
                    <button
                      onClick={() => setConfirming(null)}
                      className="px-2 py-0.5 rounded-full bg-white/10 hover:bg-white/20 text-on-surface-variant text-lg font-bold transition-colors"
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
      <span className="text-base text-on-surface-variant">불러오는 중...</span>
    </div>
  )
  if (error) return <p className="text-red-400 text-lg p-8">{error}</p>

  const byType = stats?.by_type ?? {}

  return (
    <div className="space-y-6">
      {/* 총합 */}
      <div className="glass-panel rounded-xl p-6 border border-primary/20 bg-primary/5">
        <p className="text-sm font-bold uppercase tracking-widest text-primary mb-2">총 벡터 데이터</p>
        <div className="flex items-end gap-6">
          <div>
            <p className="text-4xl font-black text-on-surface">{stats?.total_chunks?.toLocaleString()}</p>
            <p className="text-sm text-on-surface-variant mt-1">총 청크 (벡터)</p>
          </div>
          <div>
            <p className="text-2xl font-black text-on-surface">{stats?.total_files}</p>
            <p className="text-sm text-on-surface-variant mt-1">총 파일</p>
          </div>
        </div>
      </div>

      {/* 타입별 컬렉션 */}
      <div className="grid grid-cols-2 gap-4">
        {[
          { key: 'video', db: 'embedded_DB/Movie',   dim: '3200d (Re+Im+Z)',  model: 'TRI-CHEF 3-axis',       col: 'cache_movie.npy',    engine: 'TRI-CHEF' },
          { key: 'doc',   db: 'embedded_DB/trichef', dim: '3200d (Re+Im+Z)',  model: 'TRI-CHEF 3-axis',       col: 'trichef_doc_page',   engine: 'TRI-CHEF' },
          { key: 'image', db: 'embedded_DB/trichef', dim: '3200d (Re+Im+Z)',  model: 'TRI-CHEF 3-axis',       col: 'trichef_image',      engine: 'TRI-CHEF' },
          { key: 'audio', db: 'embedded_DB/Rec',     dim: '3200d (Re+Im+Z₀)', model: 'TRI-CHEF 2-axis+zero',  col: 'cache_music.npy',    engine: 'TRI-CHEF' },
        ].map(({ key, db, dim, model, col, engine }) => {
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
                <span className={`text-sm font-bold px-2 py-0.5 rounded-full border ${color} bg-white/5 border-white/10`}>{dim}</span>
              </div>
              <div className="space-y-2 text-base">
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
                  <span className="font-mono text-on-surface-variant/60 text-right max-w-[55%] text-lg leading-snug">{model}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">컬렉션</span>
                  <span className="font-mono text-on-surface-variant/60 text-lg">{col}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">엔진</span>
                  <span className={`font-bold text-lg ${engine === 'TRI-CHEF' ? 'text-emerald-400' : 'text-[#85adff]'}`}>{engine}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">경로</span>
                  <span className="font-mono text-on-surface-variant/50 text-lg">{db}</span>
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

      {/* 벡터 엔진 정보 */}
      <div className="glass-panel rounded-xl p-5 border border-outline-variant/10">
        <p className="text-sm font-bold uppercase tracking-widest text-secondary mb-3">벡터 엔진 정보</p>
        <div className="grid grid-cols-2 gap-4 text-base">
          {[
            ['문서 / 이미지 엔진', 'TRI-CHEF (ChromaDB)'],
            ['동영상 / 음성 엔진', 'TRI-CHEF (NPY 캐시)'],
            ['문서/이미지 유사도', 'Hermitian Score √(Re²+0.16Im²+0.04Z²)'],
            ['동영상/음성 유사도', 'Cosine (Re·Im·Z 3축 가중 합산)'],
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

  // path → { indexed, domain } 캐시. 폴더가 펼쳐질 때마다 누적.
  const [indexedMap, setIndexedMap] = useState({})
  const registerPaths = useCallback(async (paths) => {
    if (!paths || paths.length === 0) return
    const results = await checkIndexed(paths)
    if (Object.keys(results).length === 0) return
    setIndexedMap(prev => ({ ...prev, ...results }))
  }, [])

  // 폴더 path → orphan(임베딩 후 삭제된) 파일 카운트.
  const [orphanMap, setOrphanMap] = useState({})
  const registerOrphans = useCallback(async (folderPath) => {
    if (!folderPath) return
    const { count } = await fetchOrphans(folderPath)
    setOrphanMap(prev => ({ ...prev, [folderPath]: count }))
  }, [])

  // 인덱싱 예상 시간 (선택 변경 시 debounced fetch).
  const [estimateData, setEstimateData] = useState(null)
  const [estimateLoading, setEstimateLoading] = useState(false)
  const estimateTimerRef = useRef(null)
  useEffect(() => {
    if (checkedPaths.size === 0) {
      setEstimateData(null)
      return
    }
    if (estimateTimerRef.current) clearTimeout(estimateTimerRef.current)
    setEstimateLoading(true)
    estimateTimerRef.current = setTimeout(async () => {
      const paths = [...checkedPaths]
      const data = await estimateIndexing(paths)
      setEstimateData(data)
      setEstimateLoading(false)
    }, 500)  // debounce
    return () => {
      if (estimateTimerRef.current) clearTimeout(estimateTimerRef.current)
    }
  }, [checkedPaths])

  const [indexing, setIndexing] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [jobError, setJobError] = useState('')
  const [modalVisible, setModalVisible] = useState(false)
  const pollRef = useRef(null)

  const stopPolling = () => {
    // setInterval 폴링(레거시) 또는 EventSource 모두 정리.
    if (pollRef.current) {
      try {
        if (typeof pollRef.current === 'number') {
          clearInterval(pollRef.current)
        } else if (typeof pollRef.current.close === 'function') {
          pollRef.current.close()
        }
      } catch {}
      pollRef.current = null
    }
  }

  // ── 영속화: 마운트 시 이전 선택 복원 ──────────────────────────────────
  useEffect(() => {
    const saved = loadIndexingState()
    if (!saved || !saved.rootPath) return
    let cancelled = false
    ;(async () => {
      setRootPath(saved.rootPath)
      setLoading(true)
      setLoadError('')
      try {
        const items = await scanPath(saved.rootPath)
        if (cancelled) return
        setRootItems(items)
        setCheckedPaths(saved.checkedPaths)
        const supported = items.filter(i => i.kind === 'file' && i.type).map(i => i.path)
        if (supported.length) registerPaths(supported)
        registerOrphans(saved.rootPath)
      } catch (e) {
        if (!cancelled) setLoadError(`복원 실패: ${e.message}. 폴더가 이동/삭제되었을 수 있습니다.`)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── 영속화: rootPath / checkedPaths 변경 시 자동 저장 ─────────────────
  useEffect(() => {
    if (rootPath) saveIndexingState({ rootPath, checkedPaths })
  }, [rootPath, checkedPaths])

  // [UX] 인덱싱 탭 진입 시 진행 중인 작업이 있으면 모달 자동 재오픈.
  // 사용자가 다른 페이지(워크스페이스 등)에서 인덱싱 사이드바를 클릭하여
  // 돌아왔을 때, 현재 진행 상황을 즉시 확인할 수 있도록 보장.
  useEffect(() => {
    if (tab === 'indexing' && indexing && !modalVisible) {
      setModalVisible(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const handleSelectFolder = async () => {
    const path = await window.electronAPI?.selectFolder()
    if (!path) return

    setRootPath(path)
    setLoadError('')
    setLoading(true)
    setRootItems([])
    setCheckedPaths(new Set())
    setIndexedMap({})
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
      registerPaths(supported)
      registerOrphans(path)
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

  // SSE 연결 + 폴링 폴백을 캡슐화한 헬퍼 — handleStartIndexing 과
  // 페이지 재진입 시 job 복원에서 동일 로직 재사용.
  const attachJobStream = useCallback((job_id) => {
    const onTerminal = (s) => {
      if (s && (s.status === 'done' || s.status === 'error' || s.status === 'stopped')) {
        stopPolling(); setIndexing(false); clearActiveJob()
        return true
      }
      return false
    }
    const startPollFallback = () => {
      pollRef.current = setInterval(async () => {
        try {
          const s = await fetchStatus(job_id)
          setJobStatus(s)
          onTerminal(s)
        } catch { stopPolling(); setIndexing(false); setJobError('상태 조회 실패') }
      }, 1000)
    }
    try {
      const es = new EventSource(`${API}/api/index/stream/${job_id}`)
      pollRef.current = es
      es.onmessage = (ev) => {
        try {
          const s = JSON.parse(ev.data)
          setJobStatus(s)
          onTerminal(s)
        } catch {}
      }
      es.onerror = () => {
        stopPolling()
        startPollFallback()
      }
    } catch {
      startPollFallback()
    }
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
      saveActiveJob(job_id)   // [재진입] 다른 페이지 이동 후 복원용
      const initial = await fetchStatus(job_id)
      setJobStatus(initial)
      attachJobStream(job_id)
    } catch { setJobError('인덱싱 시작 실패'); setIndexing(false); setModalVisible(false) }
  }

  // [재진입] 컴포넌트 마운트 시 활성 job 자동 복구.
  // 사용자가 워크스페이스 등 다른 페이지로 갔다가 돌아오면 진행 상황 복원.
  useEffect(() => {
    const savedJobId = loadActiveJob()
    if (!savedJobId) return
    let cancelled = false
    ;(async () => {
      try {
        const status = await fetchStatus(savedJobId)
        if (cancelled) return
        const isTerminal = ['done', 'error', 'stopped'].includes(status?.status)
        if (status && !status.error && !isTerminal) {
          // 진행 중인 job — UI 복원 + SSE 재연결
          setJobId(savedJobId)
          setJobStatus(status)
          setIndexing(true)
          setModalVisible(true)
          attachJobStream(savedJobId)
        } else {
          // 종료/존재X → localStorage 정리
          clearActiveJob()
        }
      } catch {
        // backend 재시작 등으로 status 조회 실패 → 정리
        clearActiveJob()
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // [재진입] unmount 시 SSE 만 닫고 backend job 은 그대로 유지.
  // pollRef 청소(stopPolling) — backend 에 /stop 요청 보내지 않음 → job 살아있음.
  useEffect(() => {
    return () => { stopPolling() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const jobResultMap = jobStatus?.results
    ? Object.fromEntries(jobStatus.results.map(r => [r.path, r]))
    : null

  const selectedCount = checkedPaths.size

  return (
    <div className="bg-surface text-on-surface flex h-screen overflow-hidden">

      {/* Sidebar */}
      <PageSidebar
        subtitle="데이터 인덱싱"
        footerExtra={selectedCount > 0 && (
          <div className="mx-3 mb-3 p-3 rounded-xl bg-primary/10 border border-primary/20">
            <p className="text-base text-primary font-bold uppercase tracking-widest mb-1">선택됨</p>
            <p className="text-xl font-black text-primary leading-none">{selectedCount}<span className="text-sm ml-1 font-normal">개 파일</span></p>
            <IndexingETA data={estimateData} loading={estimateLoading} />
          </div>
        )}
        footerSub={
          <button onClick={() => navigate('/settings')} className="text-base text-on-surface-variant hover:text-primary transition-colors">
            설정 →
          </button>
        }
      >
        {[
          { icon: 'database',      label: '워크스페이스', onClick: () => navigate('/search') },
          { icon: 'hub',           label: '데이터 소스',  tab: 'sources'  },
          { icon: 'account_tree',  label: '인덱싱',       tab: 'indexing' },
          { icon: 'memory',        label: '벡터 저장소',  tab: 'store'    },
        ].map(item => (
          <button
            key={item.label}
            onClick={item.onClick ?? (() => setTab(item.tab))}
            className={`w-full flex items-center gap-3 rounded-xl px-4 py-2.5 text-base font-manrope uppercase tracking-widest transition-all
              ${item.tab === tab
                ? 'text-primary bg-[#1c253e]'
                : 'text-[#a5aac2] hover:bg-[#1c253e]/50 hover:text-[#dfe4fe]'}`}
          >
            <span className="material-symbols-outlined text-base">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </PageSidebar>

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
              <h2 className="text-2xl font-black text-on-surface mb-5">데이터 소스</h2>
              <DataSourcesTab />
            </div>
          )}

          {/* 탭: 벡터 저장소 */}
          {tab === 'store' && (
            <div className="flex-1 overflow-y-auto min-h-0">
              <h2 className="text-2xl font-black text-on-surface mb-5">벡터 저장소</h2>
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
              className="shrink-0 px-4 py-2 rounded-full bg-surface-container-high border border-outline-variant/40 hover:bg-surface-container-highest transition-all text-lg font-semibold flex items-center gap-2 disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-base">folder_shared</span>
              {loading ? '스캔 중...' : '폴더 선택'}
            </button>
            <span className="text-sm font-mono text-on-surface-variant/50 flex-1 truncate">
              {rootPath || '폴더를 선택하세요'}
            </span>
            {rootItems.length > 0 && (
              <span className="shrink-0 px-2.5 py-0.5 rounded-full bg-primary/10 text-primary text-base font-bold">
                {rootItems.length}개
              </span>
            )}
          </div>

          {/* 파일 트리 */}
          <div className="flex-1 glass-panel rounded-xl border border-outline-variant/15 overflow-hidden flex flex-col min-h-0">
            <div className="shrink-0 px-4 py-2.5 border-b border-outline-variant/10 flex items-center justify-between">
              <h2 className="text-base font-bold tracking-tight text-on-surface">리소스 탐색기</h2>
              <div className="flex items-center gap-2">
                <SelectNewOnlyButton
                  indexedMap={indexedMap}
                  onApply={(paths) => setCheckedPaths(new Set(paths))}
                />
                {jobStatus && (
                <button
                  onClick={() => setModalVisible(true)}
                  className={`flex items-center gap-1.5 text-base font-bold uppercase px-2.5 py-0.5 rounded-full transition-all hover:brightness-125
                    ${jobStatus.status === 'done' ? 'bg-emerald-500/15 text-emerald-400'
                    : jobStatus.status === 'error' ? 'bg-red-500/15 text-red-400'
                    : 'bg-primary/10 text-primary'}`}
                >
                  {jobStatus.status === 'running' && <span className="material-symbols-outlined text-base animate-spin">progress_activity</span>}
                  {jobStatus.status === 'done' ? '완료' : jobStatus.status === 'error' ? '오류' : '처리 중'}
                </button>
              )}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto py-1.5 min-h-0">
              {loading && (
                <div className="flex items-center justify-center gap-2 py-12">
                  <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
                  <span className="text-base text-on-surface-variant">스캔 중...</span>
                </div>
              )}
              {!loading && loadError && (
                <div className="flex flex-col items-center gap-2 py-12">
                  <span className="material-symbols-outlined text-red-400 text-3xl">wifi_off</span>
                  <p className="text-sm text-red-400">{loadError}</p>
                  <p className="text-sm text-on-surface-variant/40">Flask 백엔드가 실행 중인지 확인하세요</p>
                </div>
              )}
              {!loading && !loadError && rootItems.length === 0 && (
                <div className="flex flex-col items-center gap-3 py-16">
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-5xl">folder_open</span>
                  <p className="text-base text-on-surface-variant/30">
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
                      indexedMap={indexedMap}
                      registerPaths={registerPaths}
                      orphanMap={orphanMap}
                      registerOrphans={registerOrphans}
                    />
                  : <FileRow
                      key={item.path} item={item} depth={0}
                      checked={checkedPaths.has(item.path)}
                      indexedInfo={indexedMap?.[item.path]}
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
              onClick={() => {
                // [UX] 인덱싱 진행 중 모달이 닫힌 상태면 클릭으로 모달 재오픈.
                // 이전: disabled 처리되어 사용자가 진행 화면으로 돌아갈 수 없었음.
                if (indexing) setModalVisible(true)
                else handleStartIndexing()
              }}
              disabled={!indexing && selectedCount === 0}
              title={indexing ? '진행 화면 다시 보기' : undefined}
              className="relative group disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <div className="absolute -inset-0.5 bg-gradient-to-r from-primary to-secondary rounded-full blur opacity-40 group-hover:opacity-70 transition duration-500" />
              <div className="relative px-10 py-3.5 bg-[#000000] rounded-full flex items-center divide-x divide-outline-variant/30">
                <span className="flex items-center gap-2.5 pr-5">
                  <span
                    className={`material-symbols-outlined text-primary ${indexing ? 'animate-spin' : 'animate-pulse'}`}
                    style={{ fontVariationSettings: '"FILL" 1' }}
                  >{indexing ? 'progress_activity' : 'rocket_launch'}</span>
                  <span className="text-on-surface font-black tracking-widest text-lg uppercase">
                    {indexing ? '진행 화면 보기' : '인덱싱 시작'}
                  </span>
                </span>
                <span className="pl-5 text-secondary text-base font-bold uppercase tracking-widest">
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
