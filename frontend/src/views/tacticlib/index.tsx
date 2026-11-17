import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { canWrite, errorMessage, fetchJson, request } from '@/api/client'

const ENDPOINT = '/api/tacticlib'
const columns = [
  '策略编号',
  '策略名称',
  '策略类型',
  '适用场景',
  '优先级',
  '策略评分',
  '使用次数',
  '首次接入批次',
  '最近使用批次',
]
const actions = ['提交策略评审', '发布策略', '退役策略']
const statuses = ['草稿', '策略评审中', '已发布', '已退役']

const pendingColumns = [
  '数据集编号',
  '推荐策略编号',
  '推荐场景',
  '预检结论',
  '场景命中结果',
  '命中策略编号',
  '策略复用次数',
  '预计复用次数',
  '预计推荐结果',
  '闭环状态',
  '业务批次',
]

type Row = Record<string, string | number | null>

export default function TacticlibView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [pending, setPending] = useState<Row[]>([])
  const [message, setMessage] = useState('')
  const [errorMessageText, setErrorMessageText] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})

  const reload = useCallback(async () => {
    const query = new URLSearchParams(filters).toString()
    try {
      const payload = await fetchJson<{ items: Row[]; total: number }>(`${ENDPOINT}?${query}`)
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
      const pendingPayload = await fetchJson<{ items: Row[] }>(`${ENDPOINT}/pending`)
      setPending(pendingPayload.items ?? [])
    } catch (error) {
      setErrorMessageText(error instanceof Error ? error.message : '策略库列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setMessage('')
    setErrorMessageText('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        setErrorMessageText(await errorMessage(response, payload.message ?? '策略库动作未生效'))
      } else {
        setMessage(payload.message)
      }
      await reload()
    } catch (error) {
      setErrorMessageText(error instanceof Error ? error.message : '策略库操作失败')
    }
  }

  const openPending = pending.filter((row) => row['闭环状态'] !== '已闭环')

  return (
    <section className="page" data-module="tacticlib">
      <header className="page-head">
        <div>
          <h2>策略库管理</h2>
          <p className="page-desc">
            维护可复用的运营策略；发布后的策略按首次接入批次进入待处理明细，推荐策略发布预检从这里读取策略记录。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn primary" to="/precheck">推荐策略发布预检</Link>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出策略库清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        <article className="stat-card">
          <span className="stat-label">运营策略总数</span>
          <strong className="stat-value">{total}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">已发布策略</span>
          <strong className="stat-value">{rows.filter((row) => row.status === '已发布').length}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">待处理预检数据集</span>
          <strong className="stat-value">{openPending.length}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">累计复用次数</span>
          <strong className="stat-value">{rows.reduce((sum, row) => sum + Number(row['使用次数'] ?? 0), 0)}</strong>
        </article>
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        <label className="filter-item">
          <span>策略编号</span>
          <input
            value={filters.keyword ?? ''}
            placeholder="按策略编号检索"
            onChange={(event) => setFilters((prev) => ({ ...prev, keyword: event.target.value }))}
          />
        </label>
        <label className="filter-item">
          <span>状态</span>
          <select
            value={filters.status ?? ''}
            onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
          >
            <option value="">全部</option>
            {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>状态</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td>{row.status}</td>
              <td className="row-actions">
                {actions.map((action) => (
                  <button
                    key={action}
                    className="link"
                    type="button"
                    disabled={!canWrite()}
                    onClick={() => void runAction(action, row)}
                  >
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 2}>暂无策略库数据，可先登记运营策略</td>
            </tr>
          )}
        </tbody>
      </table>

      <section className="section-block">
        <header className="section-head">
          <h3>运营策略库待处理明细</h3>
          <p className="page-desc">
            承接推荐策略发布预检明细数据集；运营人员据同一记录核对场景命中结果、策略复用次数与预计推荐结果，批次可追溯。
          </p>
        </header>
        <table className="data-table">
          <thead>
            <tr>{pendingColumns.map((column) => <th key={column}>{column}</th>)}</tr>
          </thead>
          <tbody>
            {pending.map((row) => (
              <tr key={String(row.id)}>
                {pendingColumns.map((column) => (
                  <td key={column}>{format(row[column])}</td>
                ))}
              </tr>
            ))}
            {pending.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={pendingColumns.length}>暂无待处理预检数据集</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <footer className="page-foot">
        <span>共 {total} 条策略库记录</span>
        {message && <span>{message}</span>}
        {errorMessageText && <span className="error-text">{errorMessageText}</span>}
      </footer>
    </section>
  )
}

function format(value: unknown): string {
  if (value === undefined || value === null || value === '') return '—'
  return String(value)
}
