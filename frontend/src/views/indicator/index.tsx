import { useCallback, useEffect, useMemo, useState } from 'react'

import { setActiveFilter } from '@/api/filter-state'
import { request } from '@/api/client'

const ENDPOINT = '/api/indicator'
const columns = [
  "指标编号",
  "指标名称",
  "计算公式",
  "统计粒度",
  "时间范围",
  "筛选条件",
  "数据来源",
  "口径版本"
]
const actions = [
  "提交审批",
  "发布指标",
  "废弃指标"
]
const statuses = [
  "草稿",
  "待审批",
  "已发布",
  "已废弃"
]

// 检索字段与列名保持一致，后端按同一筛选契约解释，名称、公式、版本可以组合。
const filterFields = ["指标编号", "指标名称", "计算公式", "口径版本"]

type Row = Record<string, string | number | null>

type Summary = {
  total?: number
  status_counts?: Record<string, number>
}

type ListPayload = {
  items?: Row[]
  total?: number
  snapshot?: string
  filters?: Record<string, string>
  summary?: Summary
}

type Criteria = Record<string, string>

export default function IndicatorView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [snapshot, setSnapshot] = useState('')
  const [summary, setSummary] = useState<Summary | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Criteria>({})
  const [status, setStatus] = useState('')
  const [detail, setDetail] = useState<Row | null>(null)

  const queryString = useCallback(() => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value.trim()) params.set(key, value.trim())
    }
    if (status) params.set('status', status)
    return params.toString()
  }, [filters, status])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = queryString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('业务指标列表读取失败')
      }
      const payload = (await response.json()) as ListPayload
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
      setSnapshot(payload.snapshot ?? '')
      // 摘要与列表来自同一张数据快照，状态计数不会各算各的。
      setSummary(payload.summary ?? null)
      // 把当前列表条件与快照交给摘要页，切换页面后统计口径仍保持一致。
      if (payload.snapshot) {
        setActiveFilter({
          module: 'indicator',
          snapshot: payload.snapshot,
          filters: payload.filters ?? {},
          total: payload.total ?? 0,
        })
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '指标口径管理列表读取失败')
    }
  }, [queryString])

  useEffect(() => {
    void reload()
  }, [reload])

  const statCards = useMemo(() => {
    const counts = summary?.status_counts ?? {}
    return [
      { label: '业务指标总数', value: summary?.total ?? total },
      { label: '已发布指标', value: counts['已发布'] ?? 0 },
      { label: '待审批指标', value: counts['待审批'] ?? 0 },
    ]
  }, [summary, total])

  function exportUrl() {
    const params = new URLSearchParams()
    const query = queryString()
    if (query) {
      for (const [key, value] of new URLSearchParams(query).entries()) {
        params.set(key, value)
      }
    }
    // 带上列表快照：文件沿用当前列表条件与同一批数据，不受之后新增记录影响。
    if (snapshot) params.set('snapshot', snapshot)
    // 要求 CSV 下载；不传 format 的既有调用仍返回原来的 JSON 结构。
    params.set('format', 'csv')
    return `${ENDPOINT}/export?${params.toString()}`
  }

  async function exportEntries() {
    setErrorMessage('')
    try {
      const response = await request(exportUrl(), { headers: { Accept: 'text/csv' } })
      if (!response.ok) {
        throw new Error('指标口径管理清单导出失败')
      }
      const text = await response.text()
      // 空结果也保留表头，浏览器下载到的是一份可识别的空文件。
      const expected = Number(response.headers.get('X-Total-Count') ?? total)
      const lines = text.trimEnd().split('\n').length
      if (expected >= 0 && lines !== expected + 1) {
        throw new Error('导出结果与当前筛选合计不一致，请刷新列表后重试')
      }
      const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = '指标口径管理清单.csv'
      link.click()
      URL.revokeObjectURL(link.href)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '指标口径管理清单导出失败')
    }
  }

  async function openDetail(row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}`)
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail ?? `业务指标 ${row.id} 读取失败`)
      }
      setDetail(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '业务指标明细读取失败')
    }
  }

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('指标口径管理动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '指标口径管理操作失败')
    }
  }

  return (
    <section className="page" data-module="indicator">
      <header className="page-head">
        <div>
          <h2>指标口径管理</h2>
          <p className="page-desc">维护业务指标的统一定义、计算口径与版本记录，保证全公司口径一致。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('业务指标登记入口尚未接入审批流')}>
            登记业务指标
          </button>
          <button className="btn" type="button" onClick={() => void exportEntries()}>
            导出指标口径管理清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {statCards.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <label className="filter-item">
          <span>状态</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">全部状态</option>
            {statuses.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => { setFilters({}); setStatus('') }}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                <button className="link" type="button" onClick={() => void openDetail(row)}>查看明细</button>
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>当前筛选条件下没有匹配的业务指标，可调整检索条件</td>
            </tr>
          )}
        </tbody>
      </table>

      {detail && (
        <section className="detail-panel">
          <header className="detail-head">
            <h3>业务指标明细</h3>
            <button className="btn ghost" type="button" onClick={() => setDetail(null)}>收起</button>
          </header>
          <dl className="detail-grid">
            {columns.map((column) => (
              <div key={column}>
                <dt>{column}</dt>
                <dd>{detail[column] ?? '—'}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <footer className="page-foot">
        <span>共 {total} 条指标口径管理记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
