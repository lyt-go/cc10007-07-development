import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { canWrite, errorMessage, fetchJson, request } from '@/api/client'

const ENDPOINT = '/api/recommend'
const columns = [
  '策略编号',
  '推荐场景',
  '召回算法',
  '排序模型',
  '冷启动策略',
  '多样性权重',
  '刷新频率',
  '推荐条数上限',
  '场景评分',
  '复用策略编号',
  '预检结论',
]
const actions = ['提交策略评审', '评审通过策略', '下线策略']
const statuses = ['草稿', '策略评审中', '评审通过', '预检通过', '已上线', '已下线']

type Row = Record<string, string | number | null>

export default function RecommendView() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [message, setMessage] = useState('')
  const [errorMessageText, setErrorMessageText] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})

  const reload = useCallback(async () => {
    const query = new URLSearchParams(filters).toString()
    try {
      const payload = await fetchJson<{ items: Row[]; total: number }>(`${ENDPOINT}?${query}`)
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessageText(error instanceof Error ? error.message : '推荐策略列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function post(path: string, body: Record<string, unknown>, redirectTo?: string) {
    setMessage('')
    setErrorMessageText('')
    try {
      const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        setErrorMessageText(await errorMessage(response, payload.message ?? '智能推荐动作未生效'))
      } else {
        setMessage(payload.message)
        if (redirectTo) {
          navigate(redirectTo)
          return
        }
      }
      await reload()
    } catch (error) {
      setErrorMessageText(error instanceof Error ? error.message : '智能推荐操作失败')
    }
  }

  return (
    <section className="page" data-module="recommend">
      <header className="page-head">
        <div>
          <h2>智能推荐管理</h2>
          <p className="page-desc">
            配置推荐场景的召回、排序与冷启动方案；上线前先执行策略复用预检，预检通过后才能进入上线列表。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn primary" to="/precheck">查看发布预检明细</Link>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出智能推荐清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        <article className="stat-card">
          <span className="stat-label">推荐策略总数</span>
          <strong className="stat-value">{total}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">已上线策略</span>
          <strong className="stat-value">{rows.filter((row) => row.status === '已上线').length}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">预检通过待上线</span>
          <strong className="stat-value">{rows.filter((row) => row.status === '预检通过').length}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">评审中策略</span>
          <strong className="stat-value">{rows.filter((row) => row.status === '策略评审中').length}</strong>
        </article>
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        <label className="filter-item">
          <span>策略编号 / 推荐场景</span>
          <input
            value={filters.keyword ?? ''}
            placeholder="按策略编号或推荐场景检索"
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
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button
                    key={action}
                    className="link"
                    type="button"
                    disabled={!canWrite()}
                    onClick={() => void post(`${ENDPOINT}/${row.id}/actions`, { action })}
                  >
                    {action}
                  </button>
                ))}
                <button
                  className="link"
                  type="button"
                  disabled={!canWrite()}
                  onClick={() => void post(`${ENDPOINT}/${row.id}/precheck`, { operator: '值班管理员' }, '/precheck')}
                >
                  发布预检
                </button>
                <button
                  className="link"
                  type="button"
                  disabled={!canWrite()}
                  onClick={() => void post(`${ENDPOINT}/${row.id}/launch`, {})}
                >
                  上线策略
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无智能推荐数据，可先登记推荐策略</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条智能推荐记录</span>
        {message && <span>{message}</span>}
        {errorMessageText && <span className="error-text">{errorMessageText}</span>}
      </footer>
    </section>
  )
}
