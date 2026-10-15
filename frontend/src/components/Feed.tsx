// The live transcript: every step of the run in order, written as plain sentences.

import { useEffect, useRef } from 'react'
import type { DeskEvent } from '../api'
import { AGENTS } from '../agents'

function argsText(args?: Record<string, unknown>) {
  if (!args) return ''
  return Object.entries(args)
    .filter(([k]) => !['requested_by', 'updated_by', 'reason', 'note'].includes(k))
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(', ')
}

function line(e: DeskEvent): { text: React.ReactNode; tone?: string } | null {
  switch (e.event) {
    case 'agent_started':
      return e.agent === 'boss'
        ? { text: 'picked up the ticket.' }
        : { text: 'joined the huddle.', tone: 'quiet' }
    case 'delegation':
      return { text: <>asked <b>{e.to_agent ? AGENTS[e.to_agent].label : '?'}</b>: “{e.request}”</> }
    case 'delegation_blocked':
      return { text: <>tried to hand off but was stopped: {e.blocked_reason}</>, tone: 'warn' }
    case 'mcp_tool_call':
      return {
        text: (
          <>
            <span className={`tool-chip ${e.write ? 'write' : ''} ${e.ok ? '' : 'fail'}`}>{e.tool}</span>
            <span className="feed-args">{argsText(e.args)}</span>
            {!e.ok && <span className="feed-fail"> refused</span>}
          </>
        ),
        tone: 'tool',
      }
    case 'mcp_tool_blocked':
      return { text: <>was blocked from <span className="tool-chip fail">{e.tool}</span> ({e.blocked_reason})</>, tone: 'warn' }
    case 'output_rejected':
      return { text: <>had a draft sent back by the guardrails: {String(e.details?.reason ?? '')}</>, tone: 'warn' }
    case 'agent_finished':
      return { text: e.said ?? 'reported back.', tone: e.agent === 'boss' ? 'decision' : 'report' }
    case 'ticket_failed':
      return { text: 'The run stopped before finishing (see the audit trail).', tone: 'warn' }
    case 'api_approval_decided':
      return { text: <>A person {String(e.details?.decision)} approval #{String(e.details?.approval_id)} ({String(e.details?.decided_by)}).</>, tone: 'human' }
    case 'api_receipt_recorded':
      return { text: <>A person recorded ${Number(e.details?.amount).toFixed(2)} received from {String(e.details?.payer)} ({String(e.details?.received_by)}).</>, tone: 'human' }
    case 'api_ticket_resolved':
      return { text: <>A person marked the ticket resolved ({String(e.details?.decided_by)}).</>, tone: 'human' }
    default:
      return null
  }
}

export function Feed({ events, live }: { events: DeskEvent[]; live: boolean }) {
  const list = useRef<HTMLOListElement>(null)
  useEffect(() => {
    // Follow the newest line inside the transcript box only (never scroll the page).
    const el = list.current
    if (live && el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [events.length, live])

  const rows = events.map((e) => ({ e, l: line(e) })).filter((r) => r.l)
  if (!rows.length) return <p className="empty">The transcript appears here once the team starts talking.</p>
  return (
    <ol className="feed" ref={list}>
      {rows.map(({ e, l }) => {
        const meta = e.agent ? AGENTS[e.agent] : undefined
        return (
          <li key={e.seq} className={`feed-row tone-${l!.tone ?? 'plain'}`} style={{ ['--agent' as string]: meta?.color ?? 'var(--ink-3)' }}>
            <span className="feed-time">{new Date(e.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</span>
            <span className="feed-who">{meta?.label ?? 'Desk'}</span>
            <span className="feed-text">{l!.text}</span>
          </li>
        )
      })}
    </ol>
  )
}
