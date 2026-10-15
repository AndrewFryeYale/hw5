// The huddle: the five agents seated around the shop's desk. While a run is live, the agent who is working
// glows, a speech bubble says what they're doing, a handoff thread is drawn from whoever delegated to them,
// and every MCP lookup lands on the ledger in the middle of the table.

import type { AgentName } from '../api'
import { AGENTS, AGENT_ORDER } from '../agents'
import type { RunView } from '../derive'

const BUBBLE_SIDE: Record<AgentName, 'below' | 'below-left' | 'below-right' | 'above'> = {
  boss: 'below',
  inventory: 'below-left',
  facilities: 'below-right',
  accounting: 'above',
  customer_service: 'above',
}

function clip(text: string | undefined, n: number) {
  if (!text) return ''
  const t = text.replace(/\s+/g, ' ').trim()
  return t.length > n ? t.slice(0, n - 1) + '…' : t
}

/** A curved thread between two seats that bows toward the middle of the table. */
function threadPath(from: AgentName, to: AgentName) {
  const a = AGENTS[from].seat, b = AGENTS[to].seat
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2
  const cx = mx + (50 - mx) * 0.55, cy = my + (50 - my) * 0.55
  return `M ${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}`
}

export function Huddle({ run, idleHint }: { run?: RunView; idleHint: string }) {
  const live = run?.running ?? false
  return (
    <div className={`huddle ${live ? 'is-live' : ''}`}>
      <svg className="huddle-threads" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
        {run?.arcs.map((arc) => (
          <path
            key={arc.seq}
            d={threadPath(arc.from, arc.to)}
            className={`thread ${arc.active ? 'active' : ''}`}
            style={{ stroke: AGENTS[arc.to].color }}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>

      <div className="huddle-table">
        <div className="ledger">
          <div className="ledger-title">Shop ledger</div>
          <div className="ledger-sub">campus-customs MCP</div>
          {run?.lastTool ? (
            <div key={run.lastTool.seq} className={`ledger-chip ${run.lastTool.write ? 'write' : ''}`}
                 style={{ borderColor: AGENTS[run.lastTool.agent].color }}>
              <span className="mono">{run.lastTool.tool}</span>
              <span className="ledger-who">{AGENTS[run.lastTool.agent].label}</span>
            </div>
          ) : (
            <div className="ledger-idle">{idleHint}</div>
          )}
        </div>
      </div>

      {AGENT_ORDER.map((name) => {
        const meta = AGENTS[name]
        const a = run?.agents[name]
        const state = a?.state ?? 'idle'
        // Working agents say what they're doing; finished agents keep their report for hover (the debrief has it all).
        const line = state === 'working' ? a?.doing : state === 'done' ? clip(a?.said, 160) : undefined
        return (
          <div key={name} className={`seat seat-${state}`}
               style={{ left: `${meta.seat.x}%`, top: `${meta.seat.y}%`, ['--agent' as string]: meta.color }}>
            <div className="seat-avatar">
              <span>{meta.initials}</span>
              {state === 'working' && <i className="seat-pulse" />}
            </div>
            <div className="seat-name">{meta.label}</div>
            <div className="seat-role">{meta.role}</div>
            {line && (
              <div className={`bubble bubble-${BUBBLE_SIDE[name]} ${state === 'working' ? 'bubble-live' : 'bubble-hover'}`}>
                {state === 'working' && <span className="typing"><i /><i /><i /></span>}
                {state === 'working' ? <em>{line}</em> : line}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

