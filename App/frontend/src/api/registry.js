// 인덱싱 UI 용 registry lookup wrapper.
// 백엔드 /api/registry/check, /api/registry/orphans 호출.

import { API_BASE as API } from '../api'

export async function checkIndexed(paths) {
  if (!paths || paths.length === 0) return {}
  try {
    const res = await fetch(`${API}/api/registry/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths }),
    })
    if (!res.ok) return {}
    const data = await res.json()
    return data.results ?? {}
  } catch {
    return {}
  }
}

// 폴더 하위에 임베딩 후 삭제된 파일(orphan) 조회.
// 사용자가 "raw_DB 에서 파일 지웠는데 registry 에 남아있는" 상태 감지.
export async function fetchOrphans(folderPath) {
  if (!folderPath) return { count: 0, orphans: [] }
  try {
    const res = await fetch(`${API}/api/registry/orphans`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: folderPath }),
    })
    if (!res.ok) return { count: 0, orphans: [] }
    const data = await res.json()
    return { count: data.count ?? 0, orphans: data.orphans ?? [] }
  } catch {
    return { count: 0, orphans: [] }
  }
}
