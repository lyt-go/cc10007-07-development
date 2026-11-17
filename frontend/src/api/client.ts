/** 统一请求封装：拼后端地址、带角色头、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export type RoleCode = 'admin' | 'ops_lead' | 'auditor' | 'analyst'

export const roleOptions: { code: RoleCode; label: string; writable: boolean }[] = [
  { code: 'admin', label: '值班管理员', writable: true },
  { code: 'ops_lead', label: '运营主管', writable: true },
  { code: 'auditor', label: '只读审计', writable: false },
  { code: 'analyst', label: '数据分析员', writable: false },
]

let currentRole: RoleCode = 'admin'

export function setOperatorRole(role: RoleCode) {
  currentRole = role
}

export function operatorRole(): RoleCode {
  return currentRole
}

export function canWrite(): boolean {
  return currentRole === 'admin' || currentRole === 'ops_lead'
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', 'X-Role': currentRole },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/** 读出后端返回的可读错误说明，权限与状态阻断都靠它展示原因。 */
export async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string; message?: string }
    return payload.detail ?? payload.message ?? fallback
  } catch {
    return fallback
  }
}
