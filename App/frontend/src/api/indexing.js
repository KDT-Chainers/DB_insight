// 인덱싱 예상 시간 fetch wrapper.
// 백엔드 /api/index/estimate 호출 → 선택 파일 목록의 예상 총 시간 반환.

import { API_BASE as API } from '../api'

export async function estimateIndexing(filePaths) {
  if (!filePaths || filePaths.length === 0) {
    return { total_seconds: 0, skipped_count: 0, new_count: 0, unsupported: 0, by_type: {} }
  }
  try {
    const res = await fetch(`${API}/api/index/estimate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: filePaths }),
    })
    if (!res.ok) return { total_seconds: 0, skipped_count: 0, new_count: 0, unsupported: 0, by_type: {} }
    return await res.json()
  } catch {
    return { total_seconds: 0, skipped_count: 0, new_count: 0, unsupported: 0, by_type: {} }
  }
}
