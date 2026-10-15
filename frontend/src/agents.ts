import type { AgentName } from './api'

export interface AgentMeta {
  name: AgentName
  label: string
  role: string
  initials: string
  color: string // token name in index.css
  seat: { x: number; y: number } // position around the huddle table, in % of the stage
}

// Boss sits at the head of the table; the four specialists sit around it.
export const AGENTS: Record<AgentName, AgentMeta> = {
  boss: { name: 'boss', label: 'Boss', role: 'Decides & requests approvals', initials: 'BO',
          color: 'var(--a-boss)', seat: { x: 50, y: 12 } },
  inventory: { name: 'inventory', label: 'Inventory', role: 'Stock, sizes & reorders', initials: 'IN',
               color: 'var(--a-inventory)', seat: { x: 88, y: 42 } },
  accounting: { name: 'accounting', label: 'Accounting', role: 'Cash, bills & margins', initials: 'AC',
                color: 'var(--a-accounting)', seat: { x: 74, y: 86 } },
  customer_service: { name: 'customer_service', label: 'Customer Service', role: 'Drafts every reply',
                      initials: 'CS', color: 'var(--a-cs)', seat: { x: 26, y: 86 } },
  facilities: { name: 'facilities', label: 'Facilities', role: 'Lease, landlord & floor', initials: 'FA',
                color: 'var(--a-facilities)', seat: { x: 12, y: 42 } },
}

export const AGENT_ORDER: AgentName[] = ['boss', 'inventory', 'accounting', 'customer_service', 'facilities']

export const TICKET_TYPE: Record<string, { label: string; icon: string }> = {
  customer_order: { label: 'Customer order', icon: '👕' },
  rent_notice: { label: 'Rent notice', icon: '🏠' },
  price_override: { label: 'Price override', icon: '🏷️' },
}

export const STATUS_LABEL: Record<string, string> = {
  open: 'Open',
  in_progress: 'In progress',
  waiting_on_approval: 'Needs approval',
  waiting_on_customer: 'Waiting on customer',
  waiting_on_vendor: 'Waiting on vendor',
  escalated: 'Escalated',
  resolved: 'Resolved',
}

export const TOOL_VERB: Record<string, string> = {
  get_ticket: 'reading the ticket',
  list_open_tickets: 'scanning the queue',
  check_stock: 'checking the shelves',
  get_invoice: 'pulling the invoice',
  get_lease: 'reading the lease',
  get_cash_position: 'checking the cash drawer',
  list_vendors: 'calling vendors',
  quote_price: 'running a quote',
  list_payments: 'checking past payments',
  list_approvals: 'checking the approval tray',
  request_approval: 'asking you to approve',
  update_ticket: 'updating the ticket',
}
