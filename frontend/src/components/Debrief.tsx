// After a run: one card per agent that took part (what they looked up, who they asked, what they reported),
// the Boss's decision, the draft reply waiting for a person, and how lean the run was.

import { AGENTS, AGENT_ORDER, STATUS_LABEL } from '../agents'
import type { RunView } from '../derive'

const SPECIALISTS = 4

export function Debrief({ run }: { run: RunView }) {
  const involved = AGENT_ORDER.filter((n) => run.agents[n].state !== 'idle')
  const specialists = involved.filter((n) => n !== 'boss').length
  const boss = run.agents.boss
  return (
    <section className="debrief">
      <div className="debrief-head">
        <h3>Debrief</h3>
        <div className="metrics">
          <Metric value={`${specialists}/${SPECIALISTS}`} label="specialists called" good={specialists <= 2} />
          <Metric value={run.metrics.delegations} label="handoffs" />
          <Metric value={run.metrics.toolCalls} label="ledger lookups" />
          <Metric value={run.metrics.tokens ? `${Math.round(run.metrics.tokens / 1000)}k` : '—'} label="tokens" />
          <Metric value={run.metrics.seconds != null ? `${run.metrics.seconds}s` : '—'} label="time" />
        </div>
      </div>

      {run.decision && (
        <div className="decision">
          <div className="decision-label">
            Boss's call {run.finalStatus && <span className="pill">{STATUS_LABEL[run.finalStatus] ?? run.finalStatus}</span>}
          </div>
          <p>{run.decision}</p>
        </div>
      )}

      <div className="debrief-grid">
        {involved.map((name) => {
          const a = run.agents[name]
          const meta = AGENTS[name]
          return (
            <article key={name} className="agent-card" style={{ ['--agent' as string]: meta.color }}>
              <header>
                <span className="mini-avatar">{meta.initials}</span>
                <div>
                  <div className="agent-card-name">{meta.label}</div>
                  <div className="agent-card-role">{meta.role}</div>
                </div>
              </header>
              {a.tools.length > 0 && (
                <div className="chips">
                  {a.tools.map((t) => (
                    <span key={t.tool} className={`tool-chip ${t.write ? 'write' : ''}`}>
                      {t.tool}{t.count > 1 ? ` ×${t.count}` : ''}
                    </span>
                  ))}
                </div>
              )}
              {a.delegatedTo.length > 0 && (
                <p className="agent-card-asked">Asked {[...new Set(a.delegatedTo)].map((d) => AGENTS[d].label).join(', ')}</p>
              )}
              {name !== 'boss' && a.reports.map((r, i) => <p key={i} className="agent-card-report">{r}</p>)}
              {a.rejections > 0 && <p className="agent-card-warn">Guardrails sent {a.rejections} draft{a.rejections > 1 ? 's' : ''} back</p>}
            </article>
          )
        })}
      </div>

      {boss.customerMessage && (
        <div className="letter">
          <div className="letter-label">Draft reply · a person reviews and sends it</div>
          <p>{boss.customerMessage}</p>
        </div>
      )}
    </section>
  )
}

function Metric({ value, label, good }: { value: string | number; label: string; good?: boolean }) {
  return (
    <div className={`metric ${good === false ? 'metric-bad' : ''}`}>
      <b>{value}</b>
      <span>{label}</span>
    </div>
  )
}
