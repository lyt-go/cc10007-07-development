import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { errorMessage, fetchJson, request } from '@/api/client'

const ENDPOINT = '/api/precheck'
const RECOMMEND_ENDPOINT = '/api/recommend'

const columns = [
  '数据集编号',
  '推荐策略编号',
  '推荐场景',
  '预检结论',
  '场景命中结果',
  '命中策略编号',
  '策略复用次数',
  '预计复用次数',
  '闭环状态',
  '业务批次',
]

const detailFields = [
  '场景归属',
  '同优先级候选',
  '裁决口径',
  '备选裁决差异',
  '多样性权重',
  '策略读取口径',
  '策略库首次接入批次',
  '预计推荐结果',
  '预检说明',
]

type Row = Record<string, string | number | boolean | null>

type PrecheckPage = { items: Row[]; total: number }

export default function PrecheckView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<Row | null>(null)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [errorMessageText, setErrorMessageText] = useState('')
  const [launchable, setLaunchable] = useState<Row[]>([])
  const [sortByNewest, setSortByNewest] = useState(true)

  const query = useMemo(() => new URLSearchParams(filters).toString(), [filters])

  const reload = useCallback(async () => {
    setErrorMessageText('')
    try {
      const payload = await fetchJson<PrecheckPage>(`${ENDPOINT}?${query}`)
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
      const pending = await fetchJson<{ items: Row[] }>(`${ENDPOINT}/launchable`)
      setLaunchable(pending.items ?? [])
    } catch (error) {
      setErrorMessageText(error instanceof Error ? error.message : '预检数据集读取失败')
    }
  }, [query])

  useEffect(() => {
    void reload()
  }, [reload])

  async function registerPrecheck(row: Row) {
    setMessage('')
    setErrorMessageText('')
    try {
      const response = await request(`${RECOMMEND_ENDPOINT}/${row['推荐策略ID']}/precheck`, {
        method: 'POST',
        body: JSON.stringify({ operator: '值班管理员' }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        setErrorMessageText(await errorMessage(response, payload.message ?? '预检登记失败'))
      } else {
        setMessage(payload.message)
        setSelected(payload.entry)
      }
      await reload()
    } catch (error) {
      setErrorMessageText(error instanceof Error ? error.message : '预检登记失败')
    }
  }

  async function launch(row: Row) {
    setMessage('')
    setErrorMessageText('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/launch`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        setErrorMessageText(await errorMessage(response, payload.message ?? '上线未生效'))
      } else {
        setMessage(payload.message)
        setSelected(payload.entry)
      }
      await reload()
    } catch (error) {
      setErrorMessageText(error instanceof Error ? error.message : '上线操作失败')
    }
  }

  const sorted = useMemo(() => {
    const copy = [...rows]
    if (sortByNewest) {
      copy.sort((a, b) => Number(b.id) - Number(a.id))
    }
    return copy
  }, [rows, sortByNewest])

  const latest = sorted[0]

  return (
    <section className="page" data-module="precheck">
      <header className="page-head">
        <div>
          <h2>推荐策略发布预检</h2>
          <p className="page-desc">
            新增推荐能力上线前，按首次接入读取推荐场景配置与策略库已发布策略，计算场景命中结果并登记预检明细数据集。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/tacticlib">去策略库待处理明细核对</Link>
          <button className="btn ghost" type="button" onClick={() => setSortByNewest((prev) => !prev)}>
            {sortByNewest ? '按批次正序查看' : '按最新批次查看'}
          </button>
        </div>
      </header>

      <div className="stat-row">
        <article className="stat-card">
          <span className="stat-label">预检明细数据集</span>
          <strong className="stat-value">{total}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">可上线（预检通过）</span>
          <strong className="stat-value">{launchable.length}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">评审中候选</span>
          <strong className="stat-value">{rows.filter((row) => row['预检结论'] === '候选').length}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">未通过</span>
          <strong className="stat-value">{rows.filter((row) => row['预检结论'] === '未通过').length}</strong>
        </article>
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        <label className="filter-item">
          <span>预检结论</span>
          <select
            value={filters.conclusion ?? ''}
            onChange={(event) => setFilters((prev) => ({ ...prev, conclusion: event.target.value }))}
          >
            <option value="">全部</option>
            <option value="通过">通过</option>
            <option value="候选">候选</option>
            <option value="未通过">未通过</option>
          </select>
        </label>
        <label className="filter-item">
          <span>推荐场景</span>
          <input
            value={filters.scenario ?? ''}
            placeholder="按推荐场景检索"
            onChange={(event) => setFilters((prev) => ({ ...prev, scenario: event.target.value }))}
          />
        </label>
        <label className="filter-item">
          <span>业务批次</span>
          <input
            value={filters.batch ?? ''}
            placeholder="按批次追溯"
            onChange={(event) => setFilters((prev) => ({ ...prev, batch: event.target.value }))}
          />
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
          {sorted.map((row) => (
            <tr key={String(row.id)} className={row.id === selected?.id ? 'row-active' : undefined}>
              {columns.map((column) => <td key={column}>{format(row[column])}</td>)}
              <td className="row-actions">
                <button className="link" type="button" onClick={() => setSelected(row)}>核对明细</button>
                <button
                  className="link"
                  type="button"
                  disabled={row['是否进入上线列表'] !== true}
                  onClick={() => void launch(row)}
                >
                  上线
                </button>
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>
                暂无预检明细数据集，请在智能推荐里对评审通过的策略执行发布预检
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {selected && (
        <article className="detail-panel">
          <header className="detail-head">
            <h3>{String(selected['数据集编号'])} · {String(selected['推荐策略编号'])}</h3>
            <button className="btn ghost" type="button" onClick={() => setSelected(null)}>收起</button>
          </header>
          <dl className="detail-grid">
            {detailFields.map((field) => (
              <div key={field}>
                <dt>{field}</dt>
                <dd>{format(selected[field])}</dd>
              </div>
            ))}
            <div>
              <dt>是否进入上线列表</dt>
              <dd>{selected['是否进入上线列表'] === true ? '是' : '否'}</dd>
            </div>
            <div>
              <dt>当前动作来源</dt>
              <dd>{format(selected['当前动作来源'])}</dd>
            </div>
          </dl>
          {selected['是否进入上线列表'] === true && (
            <button className="btn primary" type="button" onClick={() => void launch(selected)}>
              按该预检结果上线
            </button>
          )}
        </article>
      )}

      {latest && (
        <aside className="notice">
          <span>最近一批：{format(latest['业务批次'])}</span>
          <span>场景唯一命中：{format(latest['命中策略编号'])}</span>
          <span>复用次数 {format(latest['策略复用次数'])} → {format(latest['预计复用次数'])}</span>
          <button className="link" type="button" onClick={() => void registerPrecheck(latest)}>重算该批次</button>
        </aside>
      )}

      <footer className="page-foot">
        <span>共 {total} 条预检明细数据集</span>
        {message && <span>{message}</span>}
        {errorMessageText && <span className="error-text">{errorMessageText}</span>}
      </footer>
    </section>
  )
}

function format(value: unknown): string {
  if (value === undefined || value === null || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}
