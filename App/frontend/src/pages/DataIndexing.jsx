import { useNavigate } from 'react-router-dom'
import { useState, useCallback, useRef, useEffect } from 'react'
import WindowControls from '../components/WindowControls'
import { API_BASE as API } from '../api'
const TYPE_ICON = { doc: 'description', video: 'movie', image: 'image', audio: 'volume_up' }
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

// ── 파일 행 ─────────────────────────────────────────────
function FileRow({ item, depth, checked, onToggle, jobResult }) {
  const icon = TYPE_ICON[item.type] ?? 'insert_drive_file'
  const sizeKB = item.size != null ? (item.size / 1024).toFixed(1) : '-'
  const supported = item.type !== null

  let statusIcon = null
  if (jobResult) {
    if (jobResult.status === 'done')
      statusIcon = <span className="material-symbols-outlined text-emerald-400 text-base shrink-0" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>
    else if (jobResult.status === 'running')
      statusIcon = <span className="material-symbols-outlined text-primary text-base shrink-0 animate-spin">progress_activity</span>
    else if (jobResult.status === 'error')
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

// ── 인덱싱 진행 모달 ────────────────────────────────────
function IndexingModal({ rootPath, selectedCount, jobStatus, onClose }) {
  const folderName = rootPath
    ? (rootPath.split('\\').pop() || rootPath.split('/').pop() || rootPath)
    : '선택된 폴더'

  const total = jobStatus?.total ?? selectedCount
  const done  = jobStatus?.done  ?? 0
  const errors = jobStatus?.errors ?? 0
  const progress = Math.round(((done + errors) / Math.max(total, 1)) * 100)
  const isDone  = jobStatus?.status === 'done'
  const isError = jobStatus?.status === 'error'
  const isRunning = !isDone && !isError

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center">
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-md" />

      {/* card */}
      <div className="relative w-full max-w-sm mx-4 rounded-2xl overflow-hidden
        bg-[#0d1530]/90 border border-white/10 backdrop-blur-xl
        shadow-[0_0_80px_rgba(133,173,255,0.18)]">

        {/* 닫기 */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 w-7 h-7 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center text-on-surface-variant hover:text-on-surface transition-all z-10"
        >
          <span className="material-symbols-outlined text-sm leading-none">close</span>
        </button>

        {/* 폴더 정보 */}
        <div className="flex items-center gap-4 p-6 pb-4">
          {/* 폴더 아이콘 */}
          <div className="relative shrink-0">
            <div className="w-16 h-16 rounded-xl bg-gradient-to-br from-[#2563eb] to-[#7c3aed] flex items-center justify-center shadow-[0_0_30px_rgba(59,91,219,0.5)]">
              <span className="material-symbols-outlined text-white text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>folder</span>
            </div>
            {/* FILES 배지 */}
            <div className="absolute -bottom-1 -left-1 bg-[#1e3a8a] border border-[#3b82f6]/40 text-[#93c5fd] text-[8px] font-black tracking-widest px-1.5 py-0.5 rounded uppercase">
              FILES
            </div>
          </div>

          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-bold text-on-surface truncate">{folderName}</h3>
            <p className="text-sm text-on-surface-variant mt-0.5">{total}개 파일</p>
          </div>
        </div>

        {/* 진행 영역 */}
        <div className="mx-4 mb-4 bg-[#0a0f1e]/80 rounded-xl p-4 border border-white/5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              {isDone ? (
                <span className="material-symbols-outlined text-emerald-400 text-xl" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>
              ) : isError ? (
                <span className="material-symbols-outlined text-red-400 text-xl" style={{ fontVariationSettings: '"FILL" 1' }}>error</span>
              ) : (
                <span className="material-symbols-outlined text-primary text-xl animate-spin">progress_activity</span>
              )}
              <span className="text-sm font-semibold text-on-surface">
                {isDone ? '인덱싱 완료' : isError ? '오류 발생' : '인덱싱 중...'}
              </span>
            </div>
            <span className="text-2xl font-black text-on-surface tabular-nums">{progress}%</span>
          </div>

          {/* 진행 바 */}
          <div className="h-1.5 bg-white/8 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                isDone ? 'bg-emerald-500'
                : isError ? 'bg-red-500'
                : 'bg-gradient-to-r from-[#85adff] to-[#ac8aff]'
              }`}
              style={{ width: `${progress}%` }}
            />
          </div>

          <p className="mt-2 text-xs text-on-surface-variant/50 tabular-nums">
            {done}/{total} 처리됨
            {errors > 0 && <span className="text-red-400 ml-1">· 오류 {errors}개</span>}
          </p>
        </div>
      </div>
    </div>
  )
}

// ── 메인 ────────────────────────────────────────────────
export default function DataIndexing() {
  const navigate = useNavigate()

  const [rootPath, setRootPath] = useState('')
  const [rootItems, setRootItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')

  const [checkedPaths, setCheckedPaths] = useState(new Set())

  const [indexing, setIndexing] = useState(false)
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
      const initial = await fetchStatus(job_id)
      setJobStatus(initial)
      pollRef.current = setInterval(async () => {
        try {
          const s = await fetchStatus(job_id)
          setJobStatus(s)
          if (s.status === 'done' || s.status === 'error') { stopPolling(); setIndexing(false) }
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
            { icon: 'database', label: '워크스페이스', onClick: () => navigate('/search') },
            { icon: 'hub', label: '데이터 소스' },
            { icon: 'account_tree', label: '인덱싱', active: true },
            { icon: 'memory', label: '벡터 저장소' },
          ].map(item => (
            <button
              key={item.label}
              onClick={item.onClick}
              className={`w-full flex items-center gap-3 rounded-xl px-4 py-2.5 text-[0.75rem] font-manrope uppercase tracking-widest transition-all
                ${item.active
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
        </div>
      </main>

      {/* 인덱싱 진행 모달 */}
      {modalVisible && (
        <IndexingModal
          rootPath={rootPath}
          selectedCount={selectedCount}
          jobStatus={jobStatus}
          onClose={() => setModalVisible(false)}
        />
      )}
    </div>
  )
}
