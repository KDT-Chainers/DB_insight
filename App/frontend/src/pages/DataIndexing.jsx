import { useNavigate } from 'react-router-dom'
import { useState } from 'react'

const FILE_TREE = [
  {
    id: 'root',
    name: 'Project_Alpha_Core',
    type: 'folder',
    status: '컨테이너',
    statusColor: 'text-[#a5aac2] bg-surface-container-highest border-outline-variant/20',
    expanded: true,
    children: [
      {
        id: 'src',
        name: 'source_data',
        type: 'folder',
        status: '준비',
        statusColor: 'text-primary bg-primary/10',
        expanded: false,
        children: [
          { id: 'f1', name: 'neural_architecture.json', type: 'file', icon: 'description', status: '준비', statusColor: 'text-primary bg-primary/10', checked: true },
          { id: 'f2', name: 'dataset_v04_raw.csv', type: 'file', icon: 'table_chart', status: '대기중', statusColor: 'text-secondary bg-secondary/10', checked: false },
          {
            id: 'logs',
            name: 'processed_logs',
            type: 'folder',
            status: '부분',
            statusColor: 'text-on-surface-variant bg-surface-container-highest',
            expanded: true,
            children: [
              { id: 'l1', name: 'node_trace_01.log', type: 'file', icon: 'analytics', status: '준비', statusColor: 'text-primary bg-primary/10', checked: true },
              { id: 'l2', name: 'node_trace_02.log', type: 'file', icon: 'analytics', status: '손상', statusColor: 'text-error bg-error/10', checked: false },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'backup',
    name: 'Backups_Legacy',
    type: 'folder',
    status: '제외',
    statusColor: 'text-[#a5aac2] bg-surface-container-highest border-outline-variant/20',
    expanded: false,
    children: [],
  },
]

function FileTreeItem({ item, depth = 0 }) {
  const [expanded, setExpanded] = useState(item.expanded ?? false)
  const [checked, setChecked] = useState(item.checked ?? (item.type === 'folder'))
  const indent = depth * 36

  return (
    <div>
      <div
        className="group flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-primary/5 transition-colors cursor-pointer"
        style={{ marginLeft: `${indent}px` }}
        onClick={() => item.type === 'folder' && setExpanded(!expanded)}
      >
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => { e.stopPropagation(); setChecked(e.target.checked) }}
          onClick={(e) => e.stopPropagation()}
          className="w-4 h-4 rounded border-outline-variant bg-transparent text-primary focus:ring-primary focus:ring-offset-0"
        />
        {item.type === 'folder' ? (
          <>
            <span className="material-symbols-outlined text-primary-container text-[20px]">
              {expanded ? 'keyboard_arrow_down' : 'keyboard_arrow_right'}
            </span>
            <span className="material-symbols-outlined text-[#85adff] text-[20px]" style={{ fontVariationSettings: '"FILL" 1' }}>folder</span>
          </>
        ) : (
          <>
            <div className="w-[20px]"></div>
            <span className="material-symbols-outlined text-on-surface-variant text-[20px]">{item.icon}</span>
          </>
        )}
        <span className="text-sm font-medium flex-1 text-on-surface-variant">{item.name}</span>
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${item.statusColor}`}>
          {item.status}
        </span>
      </div>
      {item.type === 'folder' && expanded && item.children?.map((child) => (
        <FileTreeItem key={child.id} item={child} depth={depth + 1} />
      ))}
    </div>
  )
}

export default function DataIndexing() {
  const navigate = useNavigate()
  const [indexMode, setIndexMode] = useState('자동')
  const [complexityMode, setComplexityMode] = useState('딥 러닝')

  return (
    <div className="bg-surface text-on-surface flex min-h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="h-screen w-64 sticky left-0 top-0 bg-[#000000] flex flex-col py-6 shadow-2xl shadow-blue-900/20 bg-gradient-to-b from-[#070d1f] to-[#000000] z-50">
        <div className="px-6 mb-10 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary-container flex items-center justify-center">
            <span className="material-symbols-outlined text-on-primary-container text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>memory</span>
          </div>
          <div>
            <h1 className="text-lg font-black text-[#85adff] font-manrope uppercase tracking-tight">Obsidian</h1>
            <p className="font-manrope uppercase text-[10px] tracking-widest text-[#a5aac2]">인텔리전스</p>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-4">
          <button onClick={() => navigate('/search')} className="w-full flex items-center gap-3 px-4 py-3 rounded-xl hover:bg-[#0c1326] hover:text-[#dfe4fe] transition-all group text-[#a5aac2]">
            <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">database</span>
            <span className="font-manrope uppercase text-[10px] tracking-widest">워크스페이스</span>
          </button>
          <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl hover:bg-[#0c1326] hover:text-[#dfe4fe] transition-all group text-[#a5aac2]">
            <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">hub</span>
            <span className="font-manrope uppercase text-[10px] tracking-widest">데이터 소스</span>
          </button>
          <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-[#1c253e] text-[#85adff] border-r-2 border-[#85adff]">
            <span className="material-symbols-outlined">account_tree</span>
            <span className="font-manrope uppercase text-[10px] tracking-widest">인덱싱</span>
          </div>
          <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl hover:bg-[#0c1326] hover:text-[#dfe4fe] transition-all group text-[#a5aac2]">
            <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">memory</span>
            <span className="font-manrope uppercase text-[10px] tracking-widest">벡터 저장소</span>
          </button>
          <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl hover:bg-[#0c1326] hover:text-[#dfe4fe] transition-all group text-[#a5aac2]">
            <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">terminal</span>
            <span className="font-manrope uppercase text-[10px] tracking-widest">API</span>
          </button>
        </nav>
        <div className="px-4 mt-auto space-y-4">
          <button className="w-full py-3 rounded-full bg-gradient-to-r from-primary to-secondary text-on-primary font-bold text-xs uppercase tracking-widest shadow-[0_0_20px_rgba(133,173,255,0.3)] hover:brightness-110 transition-all active:scale-95">
            새 인덱스
          </button>
          <div className="pt-4 border-t border-[#41475b]/20 space-y-1">
            <button onClick={() => navigate('/settings')} className="w-full flex items-center gap-3 px-4 py-2 text-[#a5aac2] hover:text-[#dfe4fe] transition-colors">
              <span className="material-symbols-outlined text-sm">shield</span>
              <span className="font-manrope uppercase text-[10px] tracking-widest">보안</span>
            </button>
            <button className="w-full flex items-center gap-3 px-4 py-2 text-[#a5aac2] hover:text-[#dfe4fe] transition-colors">
              <span className="material-symbols-outlined text-sm">sensors</span>
              <span className="font-manrope uppercase text-[10px] tracking-widest">상태</span>
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 flex flex-col relative overflow-hidden bg-surface-dim">
        {/* Background glows */}
        <div className="absolute top-[-10%] right-[-10%] w-[600px] h-[600px] bg-primary/10 rounded-full blur-[120px] pointer-events-none"></div>
        <div className="absolute bottom-[-10%] left-[20%] w-[400px] h-[400px] bg-secondary/5 rounded-full blur-[100px] pointer-events-none"></div>

        {/* Top bar */}
        <header className="w-full top-0 sticky bg-[#070d1f]/60 backdrop-blur-xl flex justify-between items-center px-6 h-16 border-b border-[#41475b]/15 shadow-[0_0_40px_rgba(133,173,255,0.1)] z-40">
          <div className="flex items-center gap-8">
            <span className="text-xl font-bold tracking-tighter text-[#dfe4fe] font-manrope">DB_insight</span>
            <nav className="hidden md:flex items-center gap-6">
              {['탐색기', '신경망 맵', '기록', '클러스터'].map((item, i) => (
                <button key={item} className={`font-manrope tracking-tight text-sm ${i === 2 ? 'text-[#85adff] border-b-2 border-[#85adff] pb-1' : 'text-[#a5aac2] hover:text-[#dfe4fe] transition-colors'}`}>{item}</button>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-container-low border border-outline-variant/30">
              <span className="material-symbols-outlined text-[#85adff] text-sm">search</span>
              <input className="bg-transparent border-none focus:ring-0 text-sm w-48 text-on-surface-variant placeholder-[#41475b] outline-none" placeholder="신경망 검색..." />
            </div>
            <button onClick={() => navigate('/settings')} className="material-symbols-outlined text-[#a5aac2] hover:text-[#dfe4fe] cursor-pointer">settings</button>
          </div>
        </header>

        {/* Content */}
        <div className="flex-1 p-8 flex flex-col gap-6 overflow-hidden">
          {/* Config row */}
          <div className="grid grid-cols-12 gap-6 items-center">
            <div className="col-span-12 lg:col-span-7 glass-panel p-6 rounded-xl border border-outline-variant/15 flex items-center justify-between gap-6">
              <div className="flex-1">
                <label className="text-[10px] uppercase tracking-[0.1em] text-primary mb-2 block font-bold">구성 경로</label>
                <div className="flex items-center gap-3 bg-surface-container-lowest/50 px-4 py-3 rounded-lg border border-outline-variant/10">
                  <span className="material-symbols-outlined text-[#a5aac2] text-sm">folder_open</span>
                  <span className="text-sm font-mono text-on-surface-variant truncate">C:/Users/Admin/Documents/Project_Alpha</span>
                </div>
              </div>
              <button className="px-6 py-3 rounded-full bg-surface-container-high border border-outline-variant/40 hover:bg-surface-container-highest transition-all text-sm font-semibold flex items-center gap-2 whitespace-nowrap">
                <span className="material-symbols-outlined text-sm">folder_shared</span>폴더 선택
              </button>
            </div>
            <div className="col-span-12 lg:col-span-5 glass-panel p-6 rounded-xl border border-outline-variant/15">
              <label className="text-[10px] uppercase tracking-[0.1em] text-secondary mb-4 block font-bold">신경망 파라미터</label>
              <div className="flex flex-col gap-4">
                {/* Index mode toggle */}
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-on-surface-variant">인덱싱 모드</span>
                  <div className="flex bg-surface-container-lowest rounded-full p-1 border border-outline-variant/20">
                    {['자동', '수동'].map((mode) => (
                      <button
                        key={mode}
                        onClick={() => setIndexMode(mode)}
                        className={`px-4 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-widest transition-all ${indexMode === mode ? 'bg-primary text-on-primary' : 'text-on-surface-variant'}`}
                      >
                        {mode}
                      </button>
                    ))}
                  </div>
                </div>
                {/* Complexity toggle */}
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-on-surface-variant">복잡도 엔진</span>
                  <div className="flex bg-surface-container-lowest rounded-full p-1 border border-outline-variant/20">
                    {['기본', '딥 러닝'].map((mode) => (
                      <button
                        key={mode}
                        onClick={() => setComplexityMode(mode)}
                        className={`px-4 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-widest transition-all ${complexityMode === mode ? 'bg-secondary text-on-secondary shadow-[0_0_15px_rgba(172,138,255,0.4)]' : 'text-on-surface-variant'}`}
                      >
                        {mode}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* File tree */}
          <div className="flex-1 glass-panel rounded-xl border border-outline-variant/15 overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-outline-variant/10 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <h2 className="text-lg font-bold tracking-tight text-on-surface">리소스 탐색기</h2>
                <span className="px-3 py-1 rounded-full bg-primary/10 text-primary text-[10px] font-bold tracking-widest uppercase">142개 항목 발견</span>
              </div>
              <div className="flex items-center gap-2">
                <button className="text-xs font-semibold text-on-surface-variant hover:text-primary transition-colors">모두 펼치기</button>
                <span className="w-px h-3 bg-outline-variant/30"></span>
                <button className="text-xs font-semibold text-on-surface-variant hover:text-primary transition-colors">모두 접기</button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
              <div className="space-y-1">
                {FILE_TREE.map((item) => (
                  <FileTreeItem key={item.id} item={item} depth={0} />
                ))}
              </div>
            </div>
          </div>

          {/* Start button */}
          <div className="flex justify-center pt-4">
            <button className="relative group">
              <div className="absolute -inset-1 bg-gradient-to-r from-primary to-secondary rounded-full blur opacity-40 group-hover:opacity-75 transition duration-1000 group-hover:duration-200"></div>
              <div className="relative px-12 py-5 bg-[#000000] rounded-full leading-none flex items-center divide-x divide-outline-variant/30">
                <span className="flex items-center space-x-5">
                  <span className="material-symbols-outlined text-primary animate-pulse" style={{ fontVariationSettings: '"FILL" 1' }}>rocket_launch</span>
                  <span className="pr-6 text-on-surface font-black tracking-widest text-sm uppercase">선택한 파일 인덱싱 시작</span>
                </span>
                <span className="pl-6 text-secondary text-xs font-bold uppercase tracking-widest">84.2 GB 대상</span>
              </div>
            </button>
          </div>
        </div>

        {/* Pulse decoration */}
        <div className="absolute bottom-8 right-8 flex items-end gap-1 h-12 pointer-events-none opacity-40">
          {[4, 8, 12, 6, 9].map((h, i) => (
            <div key={i} className={`w-1 rounded-full ${i % 2 === 0 ? 'bg-primary' : 'bg-secondary'}`} style={{ height: `${h * 4}px` }}></div>
          ))}
        </div>
      </main>
    </div>
  )
}
