import { useNavigate } from 'react-router-dom'
import { useState, useCallback, useRef } from 'react'

const API = 'http://localhost:5001'

const TYPE_ICON = { doc: 'description', video: 'movie', image: 'image', audio: 'volume_up' }

// 폴더/파일 1단계 스캔
async function scanPath(path) {
  const res = await fetch(`${API}/api/index/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) throw new Error('Scan failed')
  const data = await res.json()
  return data.items ?? []
}

// 인덱싱 시작
async function startIndexing(filePaths) {
  const res = await fetch(`${API}/api/index/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ files: filePaths }),
  })
  if (!res.ok) throw new Error('Start failed')
  return res.json()
}

// 상태 조회
async function fetchStatus(jobId) {
  const res = await fetch(`${API}/api/index/status/${jobId}`)
  if (!res.ok) throw new Error('Status failed')
  return res.json()
}

// ── 파일 행 ──────────────────────────────────────────────
function FileRow({ item, checked, onToggle, jobResult }) {
  const icon = TYPE_ICON[item.type] ?? 'insert_drive_file'
  const sizeKB = item.size != null ? (item.size / 1024).toFixed(1) : '-'
  const supported = item.type !== null

  // 인덱싱 결과 아이콘
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
    <div className={`flex items-center gap-2 py-1 px-2 rounded hover:bg-white/5 transition-colors ${!supported ? 'opacity-40' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={!supported}
        onChange={() => supported && onToggle(item.path)}
        className="w-3 h-3 rounded border-outline-variant bg-transparent text-primary focus:ring-0 focus:ring-offset-0 shrink-0"
      />
      <span className="material-symbols-outlined text-on-surface-variant text-[14px] shrink-0">{icon}</span>
      <span className="text-xs text-on-surface-variant flex-1 truncate">{item.name}</span>
      <span className="text-[10px] text-on-surface-variant/40 shrink-0">{sizeKB} KB</span>
      {statusIcon}
    </div>
  )
}

// ── 폴더 행 (lazy) ───────────────────────────────────────
function FolderRow({ item, depth, checkedPaths, onToggleFile, onToggleFolder, jobResultMap }) {
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [children, setChildren] = useState(null)

  const handleExpand = async () => {
    if (!expanded && children === null) {
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
    setExpanded(v => !v)
  }

  const indent = depth * 14

  return (
    <div>
      <div
        className="flex items-center gap-2 py-1 px-2 rounded hover:bg-white/5 transition-colors cursor-pointer"
        style={{ paddingLeft: `${8 + indent}px` }}
        onClick={handleExpand}
      >
        <span className="material-symbols-outlined text-on-surface-variant/60 text-[14px] shrink-0">
          {loading ? 'hourglass_empty' : expanded ? 'keyboard_arrow_down' : 'keyboard_arrow_right'}
        </span>
        <span className="material-symbols-outlined text-[#85adff] text-[14px] shrink-0"
          style={{ fontVariationSettings: '"FILL" 1' }}>folder</span>
        <span className="text-xs text-on-surface-variant flex-1 truncate">{item.name}</span>
      </div>

      {expanded && children !== null && (
        <div style={{ paddingLeft: `${indent + 14}px` }}>
          {children.length === 0 && (
            <p className="text-[10px] text-on-surface-variant/30 px-2 py-1">비어 있음</p>
          )}
          {children.map(child =>
            child.kind === 'folder'
              ? <FolderRow key={child.path} item={child} depth={depth + 1}
                  checkedPaths={checkedPaths} onToggleFile={onToggleFile} onToggleFolder={onToggleFolder}
                  jobResultMap={jobResultMap} />
              : <div key={child.path} style={{ paddingLeft: '0px' }}>
                  <FileRow item={child} checked={checkedPaths.has(child.path)} onToggle={onToggleFile}
                    jobResult={jobResultMap?.[child.path]} />
                </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── 메인 페이지 ──────────────────────────────────────────
export default function DataIndexing() {
  const navigate = useNavigate()

  const [folderPath, setFolderPath] = useState('')
  const [rootItems, setRootItems] = useState([])
  const [checkedPaths, setCheckedPaths] = useState(new Set())
  const [scanning, setScanning] = useState(false)
  const [scanError, setScanError] = useState('')

  // 인덱싱 상태
  const [indexing, setIndexing] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)   // { status, total, done, errors, results }
  const [jobError, setJobError] = useState('')
  const pollRef = useRef(null)

  const handleSelectFolder = async () => {
    const path = await window.electronAPI?.selectFolder()
    if (!path) return

    setFolderPath(path)
    setScanError('')
    setScanning(true)
    setRootItems([])
    setCheckedPaths(new Set())
    // 이전 인덱싱 결과 초기화
    stopPolling()
    setJobId(null)
    setJobStatus(null)
    setJobError('')
    setIndexing(false)

    try {
      const items = await scanPath(path)
      setRootItems(items)
      // 지원 파일 기본 체크
      const supported = items.filter(i => i.kind === 'file' && i.type).map(i => i.path)
      setCheckedPaths(new Set(supported))
    } catch {
      setScanError('서버에 연결할 수 없습니다. Flask 백엔드를 실행하세요.')
    } finally {
      setScanning(false)
    }
  }

  const toggleFile = useCallback((path) => {
    setCheckedPaths(prev => {
      const next = new Set(prev)
      next.has(path) ? next.delete(path) : next.add(path)
      return next
    })
  }, [])

  // 폴링 중단
  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
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

      // 즉시 1회 조회
      const initial = await fetchStatus(job_id)
      setJobStatus(initial)

      // 1초마다 폴링
      pollRef.current = setInterval(async () => {
        try {
          const s = await fetchStatus(job_id)
          setJobStatus(s)
          if (s.status === 'done' || s.status === 'error') {
            stopPolling()
            setIndexing(false)
          }
        } catch {
          stopPolling()
          setIndexing(false)
          setJobError('상태 조회 실패')
        }
      }, 1000)
    } catch {
      setJobError('인덱싱 시작에 실패했습니다.')
      setIndexing(false)
    }
  }

  // results 배열 → path 기준 Map
  const jobResultMap = jobStatus?.results
    ? Object.fromEntries(jobStatus.results.map(r => [r.path, r]))
    : null

  const selectedCount = checkedPaths.size

  // 진행률
  const progress = jobStatus
    ? Math.round(((jobStatus.done + jobStatus.errors) / Math.max(jobStatus.total, 1)) * 100)
    : 0

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
          <button onClick={() => navigate('/settings')}
            className="material-symbols-outlined text-[#a5aac2] hover:text-[#dfe4fe] text-sm cursor-pointer">settings</button>
        </header>

        {/* Content */}
        <div className="flex-1 flex flex-col gap-3 p-4 overflow-hidden">

          {/* 경로 + 폴더 선택 */}
          <div className="shrink-0 glass-panel px-4 py-3 rounded-xl border border-outline-variant/15 flex items-center gap-3">
            <span className="material-symbols-outlined text-[#a5aac2] text-sm shrink-0">folder_open</span>
            <span className="text-xs font-mono text-on-surface-variant flex-1 truncate">
              {folderPath || '폴더를 선택하세요'}
            </span>
            <button
              onClick={handleSelectFolder}
              disabled={scanning || indexing}
              className="shrink-0 px-3 py-1.5 rounded-full bg-surface-container-high border border-outline-variant/40 hover:bg-surface-container-highest transition-all text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-sm">folder_shared</span>
              {scanning ? '스캔 중...' : '폴더 선택'}
            </button>
          </div>

          {/* 파일 트리 */}
          <div className="flex-1 glass-panel rounded-xl border border-outline-variant/15 overflow-hidden flex flex-col min-h-0">
            <div className="shrink-0 px-4 py-2 border-b border-outline-variant/10 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold tracking-tight text-on-surface">리소스 탐색기</h2>
                {rootItems.length > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[10px] font-bold tracking-widest uppercase">
                    {rootItems.length}개
                  </span>
                )}
              </div>
              {/* 인덱싱 진행 요약 */}
              {jobStatus && (
                <div className="flex items-center gap-2">
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
            </div>

            {/* 진행바 */}
            {jobStatus && jobStatus.status === 'running' && (
              <div className="shrink-0 h-0.5 bg-surface-container-high">
                <div
                  className="h-full bg-gradient-to-r from-primary to-secondary transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
            )}

            <div className="flex-1 overflow-y-auto py-1 px-1 min-h-0">
              {scanError && (
                <p className="text-xs text-red-400 text-center py-6">{scanError}</p>
              )}
              {!scanError && rootItems.length === 0 && (
                <p className="text-xs text-on-surface-variant/30 text-center py-10">
                  {folderPath ? '항목이 없습니다.' : '폴더를 선택하면 파일 목록이 표시됩니다.'}
                </p>
              )}
              {rootItems.map(item =>
                item.kind === 'folder'
                  ? <FolderRow key={item.path} item={item} depth={0}
                      checkedPaths={checkedPaths} onToggleFile={toggleFile}
                      jobResultMap={jobResultMap} />
                  : <FileRow key={item.path} item={item}
                      checked={checkedPaths.has(item.path)} onToggle={toggleFile}
                      jobResult={jobResultMap?.[item.path]} />
              )}
            </div>
          </div>

          {/* 하단: 에러 + 인덱싱 버튼 */}
          <div className="shrink-0 flex flex-col items-center gap-2 pb-1">
            {jobError && (
              <p className="text-xs text-red-400">{jobError}</p>
            )}
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
                  >
                    {indexing ? 'progress_activity' : 'rocket_launch'}
                  </span>
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
