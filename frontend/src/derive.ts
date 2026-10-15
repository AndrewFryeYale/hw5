// Turns the raw audit events for one ticket into what the board draws: who is working, what they said,
// who handed work to whom, and (after the run) a per-agent debrief.

import type { AgentName, DeskEvent } from './api'
import { AGENT_ORDER, TOOL_VERB, AGENTS } from './agents'

export type AgentState = 'idle' | 'working' | 'done'

export interface AgentLive {
  state: AgentState
  said?: string // latest thing they reported or asked
  doing?: string // what they are doing right now (while working)
  tools: { tool: string; count: number; write: boolean }[]
  reports: string[] // each finished report (an agent can be asked twice)
  delegatedTo: AgentName[]
  customerMessage?: string
  rejections: number
  tokens?: number
}

export interface Arc {
  from: AgentName
  to: AgentName
  active: boolean
  seq: number
}

export interface RunView {
  runId: string
  events: DeskEvent[]
  running: boolean
  failed: boolean
  decision?: string
  finalStatus?: string
  agents: Record<AgentName, AgentLive>
  arcs: Arc[]
  lastTool?: { agent: AgentName; tool: string; seq: number; write: boolean }
  metrics: { delegations: number; toolCalls: number; writes: number; tokens?: number; seconds?: number }
}

const RUN_EVENTS = new Set([
  'ticket_started', 'ticket_finished', 'ticket_failed', 'agent_started', 'agent_finished',
  'delegation', 'delegation_blocked', 'mcp_tool_call', 'mcp_tool_blocked', 'output_rejected',
])

/** The newest agent run on this ticket that happened after the last database reset. */
export function latestRun(events: DeskEvent[], lastResetSeq: number): RunView | undefined {
  const starts = events.filter((e) => e.event === 'ticket_started' && e.seq > lastResetSeq)
  const start = starts[starts.length - 1]
  if (!start) return undefined
  return buildRun(events.filter((e) => e.run_id === start.run_id && e.seq >= start.seq && RUN_EVENTS.has(e.event)))
}

function emptyAgent(): AgentLive {
  return { state: 'idle', tools: [], reports: [], delegatedTo: [], rejections: 0 }
}

function buildRun(events: DeskEvent[]): RunView {
  const agents = Object.fromEntries(AGENT_ORDER.map((a) => [a, emptyAgent()])) as Record<AgentName, AgentLive>
  const depth: Partial<Record<AgentName, number>> = {}
  const arcs: Arc[] = []
  let lastTool: RunView['lastTool']
  let finished: DeskEvent | undefined
  let failed = false
  let delegations = 0, toolCalls = 0, writes = 0

  for (const e of events) {
    const a = e.agent ? agents[e.agent] : undefined
    switch (e.event) {
      case 'agent_started':
        if (!e.agent || !a) break
        depth[e.agent] = (depth[e.agent] ?? 0) + 1
        a.state = 'working'
        a.doing = 'thinking it through'
        break
      case 'agent_finished':
        if (!e.agent || !a) break
        depth[e.agent] = Math.max(0, (depth[e.agent] ?? 1) - 1)
        if (!depth[e.agent]) a.state = 'done'
        a.doing = undefined
        if (e.said) { a.said = e.said; a.reports.push(e.said) }
        if (e.customer_message) a.customerMessage = e.customer_message
        if (e.tokens != null && e.agent === 'boss') a.tokens = e.tokens
        for (const arc of arcs) if (arc.to === e.agent && arc.active) arc.active = false
        break
      case 'delegation':
        if (!a || !e.to_agent) break
        delegations++
        a.delegatedTo.push(e.to_agent)
        a.doing = `waiting on ${AGENTS[e.to_agent].label}`
        a.said = e.request
        arcs.push({ from: e.agent!, to: e.to_agent, active: true, seq: e.seq })
        break
      case 'mcp_tool_call': {
        if (!a || !e.tool) break
        toolCalls++
        if (e.write) writes++
        const t = a.tools.find((x) => x.tool === e.tool)
        if (t) t.count++
        else a.tools.push({ tool: e.tool, count: 1, write: !!e.write })
        a.doing = TOOL_VERB[e.tool] ?? e.tool
        lastTool = { agent: e.agent!, tool: e.tool, seq: e.seq, write: !!e.write }
        break
      }
      case 'output_rejected':
        if (a) { a.rejections++; a.doing = 'fixing a draft the guardrails rejected' }
        break
      case 'ticket_finished':
        finished = e
        break
      case 'ticket_failed':
        failed = true
        break
    }
  }

  const running = !finished && !failed
  const first = events[0], last = events[events.length - 1]
  const seconds = first && last ? Math.round((Date.parse(last.ts) - Date.parse(first.ts)) / 1000) : undefined
  return {
    runId: events[0]?.run_id ?? '',
    events,
    running,
    failed,
    decision: finished?.said,
    finalStatus: finished?.status,
    agents,
    arcs,
    lastTool,
    metrics: { delegations, toolCalls, writes, tokens: finished?.tokens, seconds },
  }
}

/** Human actions on this ticket after the last reset (approvals, manual resolve). */
export function deskActions(events: DeskEvent[], lastResetSeq: number): DeskEvent[] {
  return events.filter((e) => e.seq > lastResetSeq && e.run_id === 'api' && e.event.startsWith('api_'))
}

const ONES = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven',
  'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']

function words(n: number): string {
  if (n === 0) return 'zero'
  if (n < 20) return ONES[n]
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? '-' + ONES[n % 10] : '')
  if (n < 1000) return ONES[Math.floor(n / 100)] + ' hundred' + (n % 100 ? ' ' + words(n % 100) : '')
  return words(Math.floor(n / 1000)) + ' thousand' + (n % 1000 ? ' ' + words(n % 1000) : '')
}

/** 2400 -> "Two thousand four hundred and 00/100", the way a check spells it out. */
export function checkWords(amount: number): string {
  const dollars = Math.floor(amount)
  const cents = Math.round((amount - dollars) * 100)
  const w = words(dollars)
  return `${w.charAt(0).toUpperCase()}${w.slice(1)} and ${String(cents).padStart(2, '0')}/100`
}

export const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })
