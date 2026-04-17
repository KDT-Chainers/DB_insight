import { useNavigate } from 'react-router-dom'
import { useState, useCallback, useRef } from 'react'
import WindowControls from '../components/WindowControls'

const API = 'http://localhost:5001'
const TYPE_ICON = { doc: 'description', video: 'movie', image: 'image', audio: 'volume_up' }

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
  // 구버전 backend는 'files', 신버전은 'items' 키 사용
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

// ── 파일 행 ─────────────────────────────────────────────
function FileRow({ item, checked, onToggle, jobResult }) {
  const icon = TYPE_ICON[item.type] ?? 'insert_drive_file'
  const sizeKB = item.size != null ? (item.size / 1024).toFixed(1) : '-'
  const supported = item.type !== null

  let statusIcon = null
  if (jobResult) {
    if (jobResult.status === 'done')
      statusIcon = <span className="material-symbols-outlined text-emerald-400 text-[13px] shrink-0" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>
    else if (jobResult.status === 'running')
      statusIcon = <span className="material-symbols-outlined text-primary text-[13px] shrink-0 animate-spin">progress_activity</span>
    else if (jobResult.status === 'error')
      statusIcon = <span className="material-symbols-outlined text-red-400 text-[13px] shrink-0" style={{ fontVariationSettings: '"FILL" 1' }}>error</span>
    else
      statusIcon = <span className="material-symbols-outlined text-on-surface-variant/30 text-[13px] shrink-0">schedule</span>
  }

  return (
    <div className={`flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-white/5 transition-colors group ${!supported ? 'opacity-40' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={!supported}
        onChange={() => supported && onToggle(item.path)}
        className="w-3 h-3 rounded border-outline-variant bg-transparent text-primary focus:ring-0 focus:ring-offset-0 shrink-0"
      />
      <span className="material-symbols-outlined text-on-surface-variant text-[15px] shrink-0">{icon}</span>
      <span className="text-xs text-on-surface flex-1 truncate">{item.name}</span>
      <span className="text-[10px] text-on-surface-variant/40 shrink-0">{sizeKB} KB</span>
      {statusIcon}
    </div>
  )
}

// ── 폴더 행 ─────────────────────────────────────────────
function FolderRow({ item, onClick }) {
  return (
    <div
      onClick={() => onClick(item)}
      className="flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-white/5 transition-colors cursor-pointer group"
    >
      <div className="w-3 h-3 shrink-0" /> {/* checkbox 자리 맞추기 */}
      <span
        className="material-symbols-outlined text-[#85adff] text-[15px] shrink-0"
        style={{ fontVariationSettings: '"FILL" 1' }}
      >folder</span>
      <span className="text-xs text-on-surface flex-1 truncate">{item.name}</span>
      <span className="material-symbols-outlined text-on-surface-variant/30 text-[13px] shrink-0 group-hover:text-on-surface-variant transition-colors">
        chevron_right
      </span>
    </div>
  )
}

// ── 브레드크럼 ───────────────────────────────────────────
function Breadcrumb({ pathStack, onNavigate }) {
  // pathStack = [{ label, path }, ...]
  return (
    <div className="flex items-center gap-0.5 flex-1 min-w-0 overflow-x-auto scrollbar-none">
      {pathStack.map((seg, i) => {
        const isLast = i === pathStack.length - 1
        return (
          <div key={seg.path} className="flex items-center gap-0.5 shrink-0">
            {i > 0 && (
              <span className="material-symbols-outlined text-on-surface-variant/30 text-[12px]">chevron_right</span>
            )}
            <button
              onClick={() => !isLast && onNavigate(i)}
              className={`text-[11px] px-1 py-0.5 rounded transition-colors max-w-[120px] truncate
                ${isLast
                  ? 'text-on-surface font-semibold cursor-default'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-white/5'}`}
            >
              {seg.label}
            </button>
          </div>
        )
      })}
    </div>
  )
}

// ── 메인 ────────────────────────────────────────────────
export default function DataIndexing() {
  const navigate = useNavigate()

  // 탐색 상태
  const [pathStack, setPathStack] = useState([])   // [{ label, path }]
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')

  // 체크 상태
  const [checkedPaths, setCheckedPaths] = useState(new Set())

  // 인덱싱 상태
  const [indexing, setIndexing] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [jobError, setJobError] = useState('')
  const pollRef = useRef(null)

  // 특정 경로 로드 (탐색기 진입)
  const loadPath = useCallback(async (path, label) => {
    setLoading(true)
    setLoadError('')
    setItems([])
    try {
      const result = await scanPath(path)
      setItems(result)
    } catch (e) {
      setLoadError(`불러오기 실패: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  // 폴더 선택 (최초 진입)
  const handleSelectFolder = async () => {
    const path = await window.electronAPI?.selectFolder()
    if (!path) return

    const label = path.split(/[\\/]/).pop() || path
    const newStack = [{ label, path }]
    setPathStack(newStack)
    setCheckedPaths(new Set())
    stopPolling()
    setJobId(null)
    setJobStatus(null)
    setJobError('')
    setIndexing(false)
    await loadPath(path, label)
  }

  // 폴더 클릭 → 그 안으로 진입
  const handleFolderClick = useCallback(async (folderItem) => {
    const label = folderItem.name
    setPathStack(prev => [...prev, { label, path: folderItem.path }])
    await loadPath(folderItem.path, label)
  }, [loadPath])

  // 브레드크럼 클릭 → 특정 레벨로 복귀
  const handleBreadcrumbNavigate = useCallback(async (index) => {
    const target = pathStack[index]
    if (!target) return
    const newStack = pathStack.slice(0, index + 1)
    setPathStack(newStack)
    await loadPath(target.path, target.label)
  }, [pathStack, loadPath])

  // 한 단계 위로
  const handleGoUp = useCallback(async () => {
    if (pathStack.length <= 1) return
    await handleBreadcrumbNavigate(pathStack.length - 2)
  }, [pathStack, handleBreadcrumbNavigate])

  // 현재 뷰의 지원 파일 전체 선택/해제
  const handleToggleAll = useCallback(() => {
    const supported = items.filter(i => i.kind === 'file' && i.type).map(i => i.path)
    const allChecked = supported.every(p => checkedPaths.has(p))
    setCheckedPaths(prev => {
      const next = new Set(prev)
      if (allChecked) supported.forEach(p => next.delete(p))
      else supported.forEach(p => next.add(p))
      return next
    })
  }, [items, checkedPaths])

  const toggleFile = useCallback((path) => {
    setCheckedPaths(prev => {
      const next = new Set(prev)
      next.has(path) ? next.delete(path) : next.add(path)
      return next
    })
  }, [])

  // 폴링 중단
  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  // 인덱싱 시작
  const handleStartIndexing = async () => {
    if (checkedPaths.size === 0) return
    setIndexing(true)
    setJobError('')
    setJobStatus(null)
    try {
      const { job_id } = await startIndexing([...checkedPaths])
      setJobId(job_id)
      const initial = await fetchStatus(job_id)
      setJobStatus(initial)
      pollRef.current = setInterval(async () => {
        try {
          const s = await fetchStatus(job_id)
          setJobStatus(s)
          if (s.status === 'done' || s.status === 'error') { stopPolling(); setIndexing(false) }
        } catch { stopPolling(); setIndexing(false); setJobError('상태 조회 실패') }
      }, 1000)
    } catch { setJobError('인덱싱 시작에 실패했습니다.'); setIndexing(false) }
  }

  const jobResultMap = jobStatus?.results
    ? Object.fromEntries(jobStatus.results.map(r => [r.path, r]))
    : null

  const currentPath = pathStack[pathStack.length - 1]?.path ?? ''
  const selectedCount = checkedPaths.size
  const progress = jobStatus
    ? Math.round(((jobStatus.done + jobStatus.errors) / Math.max(jobStatus.total, 1)) * 100)
    : 0

  // 현재 뷰의 지원 파일
  const supportedInView = items.filter(i => i.kind === 'file' && i.type).map(i => i.path)
  const allViewChecked = supportedInView.length > 0 && supportedInView.every(p => checkedPaths.has(p))

  return (
    <div className="bg-surface text-on-surface flex h-screen overflow-hidden">

      {/* Sidebar */}
      <aside className="w-52 shrink-0 h-screen bg-gradient-to-b from-[#070d1f] to-[#000000] flex flex-col py-4 shadow-2xl shadow-blue-900/20 z-50">
        <div className="px-4 mb-6 flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-primary-container flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-on-primary-container text-xs" style={{ fontVariationSettings: '"FILL" 1' }}>memory</span>
          </div>
          <div>
            <h1 className="text-sm font-black text-[#85adff] font-manrope uppercase tracking-tight leading-none">Obsidian</h1>
            <p className="font-manrope uppercase text-[8px] tracking-widest text-[#a5aac2]">인텔리전스</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 px-2">
          {[
            { icon: 'database', label: '워크스페이스', onClick: () => navigate('/search') },
            { icon: 'hub', label: '데이터 소스' },
            { icon: 'account_tree', label: '인덱싱', active: true },
            { icon: 'memory', label: '벡터 저장소' },
          ].map(item => (
            <button
              key={item.label}
              onClick={item.onClick}
              className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[10px] font-manrope uppercase tracking-widest transition-all
                ${item.active
                  ? 'bg-[#1c253e] text-[#85adff] border-r-2 border-[#85adff]'
                  : 'text-[#a5aac2] hover:bg-[#0c1326] hover:text-[#dfe4fe]'}`}
            >
              <span className="material-symbols-outlined text-sm">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        {/* 선택 현황 요약 */}
        {selectedCount > 0 && (
          <div className="mx-3 mb-3 p-2.5 rounded-xl bg-primary/10 border border-primary/20">
            <p className="text-[10px] text-primary font-bold uppercase tracking-widest mb-1">선택됨</p>
            <p className="text-lg font-black text-primary leading-none">{selectedCount}<span className="text-xs ml-1 font-normal">개 파일</span></p>
          </div>
        )}

        <div className="px-3 mt-auto space-y-2">
          <button className="w-full py-2 rounded-full bg-gradient-to-r from-primary to-secondary text-on-primary font-bold text-[10px] uppercase tracking-widest hover:brightness-110 transition-all active:scale-95">
            새 인덱스
          </button>
          <button onClick={() => navigate('/settings')}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-[#a5aac2] hover:text-[#dfe4fe] transition-colors text-[10px] font-manrope uppercase tracking-widest">
            <span className="material-symbols-outlined text-sm">shield</span>보안
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden bg-surface-dim relative">
        <div className="absolute top-0 right-0 w-96 h-96 bg-primary/10 rounded-full blur-[120px] pointer-events-none" />

        {/* Top bar */}
        <header className="shrink-0 bg-[#070d1f]/60 backdrop-blur-xl flex justify-between items-center px-4 h-12 border-b border-[#41475b]/15 z-40">
          <span className="text-sm font-bold tracking-tighter text-[#dfe4fe] font-manrope">DB_insight</span>
          <div className="flex items-center gap-2">
            <button onClick={() => navigate('/settings')}
              className="material-symbols-outlined text-[#a5aac2] hover:text-[#dfe4fe] text-sm cursor-pointer">settings</button>
            <div className="w-px h-4 bg-white/10 mx-1" />
            <WindowControls />
          </div>
        </header>

        {/* Content */}
        <div className="flex-1 flex flex-col gap-3 p-4 overflow-hidden">

          {/* 폴더 선택 바 */}
          <div className="shrink-0 glass-panel px-3 py-2 rounded-xl border border-outline-variant/15 flex items-center gap-2">
            <button
              onClick={handleSelectFolder}
              disabled={loading || indexing}
              className="shrink-0 px-3 py-1.5 rounded-full bg-surface-container-high border border-outline-variant/40 hover:bg-surface-container-highest transition-all text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-sm">folder_shared</span>
              {loading ? '로딩 중...' : '폴더 선택'}
            </button>

            {/* 뒤로 가기 */}
            {pathStack.length > 1 && (
              <button
                onClick={handleGoUp}
                disabled={loading}
                className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center bg-surface-container-high border border-outline-variant/30 hover:bg-surface-container-highest transition-all disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[13px] text-on-surface-variant">arrow_back</span>
              </button>
            )}

            {/* 브레드크럼 */}
            {pathStack.length > 0
              ? <Breadcrumb pathStack={pathStack} onNavigate={handleBreadcrumbNavigate} />
              : <span className="text-xs font-mono text-on-surface-variant/40 flex-1">폴더를 선택하세요</span>
            }

            {/* 아이템 수 */}
            {items.length > 0 && (
              <span className="shrink-0 px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[10px] font-bold">
                {items.length}개
              </span>
            )}
          </div>

          {/* 파일 목록 */}
          <div className="flex-1 glass-panel rounded-xl border border-outline-variant/15 overflow-hidden flex flex-col min-h-0">

            {/* 헤더 */}
            <div className="shrink-0 px-3 py-2 border-b border-outline-variant/10 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold tracking-tight text-on-surface">리소스 탐색기</h2>
              </div>
              <div className="flex items-center gap-2">
                {/* 인덱싱 진행 요약 */}
                {jobStatus && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-on-surface-variant/60">
                      {jobStatus.done}/{jobStatus.total}
                      {jobStatus.errors > 0 && <span className="text-red-400 ml-1">오류 {jobStatus.errors}</span>}
                    </span>
                    <span className={`text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full
                      ${jobStatus.status === 'done' ? 'bg-emerald-500/15 text-emerald-400'
                      : jobStatus.status === 'error' ? 'bg-red-500/15 text-red-400'
                      : 'bg-primary/10 text-primary'}`}>
                      {jobStatus.status === 'done' ? '완료' : jobStatus.status === 'error' ? '오류' : '처리 중'}
                    </span>
                  </div>
                )}
                {/* 전체 선택 */}
                {supportedInView.length > 0 && (
                  <button
                    onClick={handleToggleAll}
                    className="text-[10px] text-on-surface-variant hover:text-on-surface transition-colors px-2 py-0.5 rounded hover:bg-white/5"
                  >
                    {allViewChecked ? '전체 해제' : '전체 선택'}
                  </button>
                )}
              </div>
            </div>

            {/* 진행 바 */}
            {jobStatus && jobStatus.status === 'running' && (
              <div className="shrink-0 h-0.5 bg-surface-container-high">
                <div
                  className="h-full bg-gradient-to-r from-primary to-secondary transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
            )}

            {/* 목록 */}
            <div className="flex-1 overflow-y-auto py-1 px-2 min-h-0">
              {/* 로딩 */}
              {loading && (
                <div className="flex items-center justify-center py-10 gap-2">
                  <span className="material-symbols-outlined text-primary text-sm animate-spin">progress_activity</span>
                  <span className="text-xs text-on-surface-variant">스캔 중...</span>
                </div>
              )}

              {/* 에러 */}
              {!loading && loadError && (
                <div className="flex flex-col items-center gap-2 py-10">
                  <span className="material-symbols-outlined text-red-400 text-2xl">wifi_off</span>
                  <p className="text-xs text-red-400 text-center">{loadError}</p>
                  <p className="text-[10px] text-on-surface-variant/50">Flask 백엔드가 실행 중인지 확인하세요</p>
                </div>
              )}

              {/* 비어 있음 */}
              {!loading && !loadError && pathStack.length > 0 && items.length === 0 && (
                <div className="flex flex-col items-center gap-2 py-10">
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-2xl">folder_off</span>
                  <p className="text-xs text-on-surface-variant/40 text-center">이 폴더는 비어 있습니다.</p>
                  <p className="text-[10px] font-mono text-on-surface-variant/25 text-center px-4 truncate max-w-full">{currentPath}</p>
                </div>
              )}

              {/* 첫 진입 전 */}
              {!loading && !loadError && pathStack.length === 0 && (
                <div className="flex flex-col items-center gap-3 py-12">
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-4xl">folder_open</span>
                  <p className="text-xs text-on-surface-variant/30">폴더를 선택하면 파일 목록이 표시됩니다.</p>
                </div>
              )}

              {/* 아이템 목록 */}
              {!loading && !loadError && items.map(item =>
                item.kind === 'folder'
                  ? <FolderRow key={item.path} item={item} onClick={handleFolderClick} />
                  : <FileRow key={item.path} item={item}
                      checked={checkedPaths.has(item.path)} onToggle={toggleFile}
                      jobResult={jobResultMap?.[item.path]} />
              )}
            </div>
          </div>

          {/* 하단: 인덱싱 버튼 */}
          <div className="shrink-0 flex flex-col items-center gap-2 pb-1">
            {jobError && <p className="text-xs text-red-400">{jobError}</p>}
            <button
              onClick={handleStartIndexing}
              disabled={selectedCount === 0 || indexing}
              className="relative group disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <div className="absolute -inset-0.5 bg-gradient-to-r from-primary to-secondary rounded-full blur opacity-40 group-hover:opacity-70 transition duration-500" />
              <div className="relative px-8 py-3 bg-[#000000] rounded-full flex items-center divide-x divide-outline-variant/30">
                <span className="flex items-center gap-2 pr-4">
                  <span
                    className={`material-symbols-outlined text-primary text-sm ${indexing ? 'animate-spin' : 'animate-pulse'}`}
                    style={{ fontVariationSettings: '"FILL" 1' }}
                  >{indexing ? 'progress_activity' : 'rocket_launch'}</span>
                  <span className="text-on-surface font-black tracking-widest text-xs uppercase">
                    {indexing ? '인덱싱 중...' : '인덱싱 시작'}
                  </span>
                </span>
                <span className="pl-4 text-secondary text-[10px] font-bold uppercase tracking-widest">
                  {selectedCount > 0 ? `${selectedCount}개 선택됨` : '파일 미선택'}
                </span>
              </div>
            </button>
          </div>

        </div>
      </main>
    </div>
  )
}
