// Typed client for the desk API (backend/main.py). Base URL comes from VITE_API_URL (see .env).

export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type AgentName = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'

export interface TicketSummary {
  id: number
  type: string
  requester: string
  subject: string
  status: string
  created_at: string
  is_resolved: boolean
  state: 'open' | 'resolved'
  agent_running: boolean
}

export interface Approval {
  id: number
  ticket_id: number | null
  kind: 'invoice' | 'rent' | 'purchase'
  ref_id: number
  sku: string | null
  size: string | null
  qty: number | null
  amount: number
  reason: string
  requested_by: string
  status: 'pending' | 'approved' | 'rejected' | 'failed'
  status_after_approval: string | null
  created_at: string
  decided_by: string | null
  decided_at: string | null
  result: string | null
}

export interface Receipt {
  id: number
  ticket_id: number | null
  payer: string
  amount: number
  account: string
  received_at: string
  memo: string
  recorded_by: string
}

export interface TicketDetail extends Omit<TicketSummary, 'is_resolved'> {
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  notes: string | null
  shop_date: string
  approvals: Approval[]
  receipts: Receipt[]
}

export interface Cash {
  account: string
  balance: number
  balance_as_of: string
  shop_date: string
  pending_approvals_total: number
  total_obligations: number
  balance_after_obligations: number
  upcoming_rent: { lease_id: number; landlord: string; amount: number; next_due: string; days_until_due: number; counted_in_obligations: boolean }[]
  warnings: string[]
}

export interface DeskEvent {
  seq: number
  ts: string
  run_id: string
  event: string
  agent?: AgentName
  ticket_id?: number
  chain?: AgentName[]
  said?: string
  customer_message?: string
  tokens?: number
  to_agent?: AgentName
  request?: string
  tool?: string
  args?: Record<string, unknown>
  ok?: boolean
  write?: boolean
  result?: unknown
  blocked_reason?: string
  status?: string
  details?: Record<string, unknown>
}

export interface RunInfo {
  run_id: string
  ticket_id: number
  status: 'running' | 'finished' | 'failed'
  error: string | null
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  tickets: () => call<{ shop_date: string; tickets: TicketSummary[] }>('/tickets'),
  ticket: (id: number) => call<TicketDetail>(`/tickets/${id}`),
  runTicket: (id: number) => post<RunInfo>(`/tickets/${id}/run`, {}),
  resolveTicket: (id: number, decided_by: string, note: string) =>
    post(`/tickets/${id}/resolve`, { decided_by, note }),
  events: (ticketId: number, since: number) =>
    call<{ latest_seq: number; last_reset_seq: number; events: DeskEvent[] }>(`/events?ticket_id=${ticketId}&since=${since}&limit=500`),
  approvals: () => call<{ approvals: Approval[] }>('/approvals?status=pending'),
  approve: (id: number, decided_by: string) => post(`/approvals/${id}/approve`, { decided_by }),
  reject: (id: number, decided_by: string) => post(`/approvals/${id}/reject`, { decided_by }),
  cash: () => call<Cash>('/cash'),
  recordReceipt: (body: { amount: number; payer: string; memo: string; received_by: string; ticket_id?: number }) =>
    post('/receipts', body),
  reset: () => post('/reset'),
}
