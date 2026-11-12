/** 当前列表的筛选条件与数据快照：页面切换后摘要页仍按同一批数据统计。 */
export type ActiveFilter = {
  module: string
  snapshot: string
  filters: Record<string, string>
  total: number
}

const STORAGE_KEY = 'workbench:active-filter'

let active: ActiveFilter | null = null

function readStorage(): ActiveFilter | null {
  if (typeof sessionStorage === 'undefined') return null
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as ActiveFilter) : null
  } catch {
    return null
  }
}

export function setActiveFilter(next: ActiveFilter): void {
  active = next
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // 存储不可用时只保留内存副本，摘要页仍能在本次会话内同步。
  }
}

export function getActiveFilter(module?: string): ActiveFilter | null {
  if (!active) active = readStorage()
  if (!active) return null
  return module ? (active.module === module ? active : null) : active
}

/** 拼出与当前列表同一快照、同一筛选条件的查询串。 */
export function activeFilterQuery(module?: string): string {
  const current = getActiveFilter(module)
  if (!current) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(current.filters)) {
    if (value) params.set(key, value)
  }
  if (current.snapshot) params.set('snapshot', current.snapshot)
  return params.toString()
}
