import { useEffect, useState } from 'react'
import type { DeskEvent, TicketDetail } from '../api'
import { STATUS_LABEL, TICKET_TYPE } from '../agents'
import type { RunView } from '../derive'
import { money } from '../derive'
import { Debrief } from './Debrief'
import { Feed } from './Feed'
import { Huddle } from './Huddle'

interface Props {
  ticket: TicketDetail
  run?: RunView
  feedEvents: DeskEvent[]
  pendingHere: number
  starting: boolean
  onStart: () => void
  onResolve: (note: string) => Promise<void>
  onReceipt: (amount: number, memo: string) => Promise<void>
}

function useElapsed(since: string | undefined, active: boolean) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [active])
  if (!since) return ''
  const s = Math.max(0, Math.round((now - Date.parse(since)) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function TicketPanel({ ticket: t, run, feedEvents, pendingHere, starting, onStart, onResolve, onReceipt }: Props) {
  const type = TICKET_TYPE[t.type] ?? { label: t.type, icon: '📄' }
  const live = t.agent_running || (run?.running ?? false)
  const resolved = t.state === 'resolved'
  const elapsed = useElapsed(run?.events[0]?.ts, live)
  const [closing, setClosing] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [receiving, setReceiving] = useState(false)
  const [amount, setAmount] = useState('')
  const [memo, setMemo] = useState('Deposit')
  const notes = (t.notes ?? '').split('\n').filter(Boolean)

  const facts: [string, string][] = []
  if (t.sku) facts.push(['Item', `${t.sku}${t.size ? ` · size ${t.size}` : ''}${t.qty ? ` · qty ${t.qty}` : ''}`])
  if (t.invoice_id) facts.push(['Invoice', `#${t.invoice_id}`])
  if (t.lease_id) facts.push(['Lease', `#${t.lease_id}`])
  facts.push(['Opened', new Date(t.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })])

  const hint = resolved ? 'This ticket is closed.' : live ? 'Waiting for the first lookup…' : 'Start the team to watch them work.'

  return (
    <div className="panel">
      <section className="ticket-head">
        <div className="ticket-head-main">
          <div className="ticket-kicker">
            <span aria-hidden>{type.icon}</span> {type.label} · #{t.id}
            <span className={`pill pill-${t.status}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
          </div>
          <h1>{t.subject}</h1>
          <p className="ticket-from">from <b>{t.requester}</b></p>
          <dl className="facts">
            {facts.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
          </dl>
        </div>

        <div className="ticket-actions">
          {resolved ? (
            <div className="stamp stamp-resolved" key={`r-${t.id}`}>Resolved</div>
          ) : (
            <>
              <button className="btn btn-primary btn-lg" disabled={live || starting} onClick={onStart}>
                {live ? <><span className="spinner" /> Team working · {elapsed}</> : starting ? 'Starting…' : run ? 'Run the team again' : 'Start the team'}
              </button>
              {!closing ? (
                <button className="btn btn-ghost" disabled={live || pendingHere > 0}
                        title={pendingHere ? 'Sign or void its checks first' : ''}
                        onClick={() => setClosing(true)}>
                  Mark resolved
                </button>
              ) : (
                <form className="close-form" onSubmit={async (e) => {
                  e.preventDefault()
                  setError(null)
                  try { await onResolve(note.trim() || 'Marked resolved at the desk.'); setClosing(false); setNote('') }
                  catch (err) { setError((err as Error).message) }
                }}>
                  <input autoFocus value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why is it done? (e.g. picked up size M)" />
                  <button className="btn btn-primary" type="submit">Close ticket</button>
                  <button className="btn btn-ghost" type="button" onClick={() => setClosing(false)}>Cancel</button>
                </form>
              )}
              {!receiving ? (
                <button className="btn btn-ghost btn-sm" disabled={live} onClick={() => setReceiving(true)}>
                  ＋ Record money received
                </button>
              ) : (
                <form className="close-form" onSubmit={async (e) => {
                  e.preventDefault()
                  setError(null)
                  const n = Number(amount)
                  if (!(n > 0)) { setError('Enter the amount received.'); return }
                  try { await onReceipt(n, memo.trim() || 'Deposit'); setReceiving(false); setAmount('') }
                  catch (err) { setError((err as Error).message) }
                }}>
                  <input className="money-input" autoFocus inputMode="decimal" value={amount}
                         onChange={(e) => setAmount(e.target.value)} placeholder={`$ from ${t.requester}`} />
                  <input value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="What for?" />
                  <button className="btn btn-primary" type="submit">Add to checking</button>
                  <button className="btn btn-ghost" type="button" onClick={() => setReceiving(false)}>Cancel</button>
                </form>
              )}
              {pendingHere > 0 && <p className="ticket-sign-hint">✍ {pendingHere} check{pendingHere > 1 ? 's' : ''} waiting for your signature →</p>}
              {error && <p className="check-error">{error}</p>}
            </>
          )}
        </div>
      </section>

      <section className="stage-row">
        <div className="card stage-card">
          <div className="card-head">
            <h3>The huddle</h3>
            <span className="card-sub">{live ? `Live · ${elapsed}` : run ? 'Last run' : 'Nobody has picked this up yet'}</span>
          </div>
          <Huddle run={run} idleHint={hint} />
        </div>
        <div className="card feed-card">
          <div className="card-head">
            <h3>Transcript</h3>
            <span className="card-sub">{run ? `${run.metrics.toolCalls} lookups · ${run.metrics.delegations} handoffs` : ''}</span>
          </div>
          <Feed events={feedEvents} live={live} />
        </div>
      </section>

      {run && !run.running && <Debrief run={run} />}

      <details className="card ticket-log" open={resolved || undefined}>
        <summary>Ticket log <span className="card-sub">{notes.length} entr{notes.length === 1 ? 'y' : 'ies'}</span></summary>
        <ol>{notes.map((n, i) => <li key={i}>{n}</li>)}</ol>
        {t.approvals.length > 0 && (
          <>
            <h4>Approvals</h4>
            <ul className="approval-history">
              {t.approvals.map((a) => (
                <li key={a.id}><span className={`pill pill-a-${a.status}`}>{a.status}</span> #{a.id} {a.kind} {money(a.amount)}{a.decided_by ? ` · ${a.decided_by}` : ''}</li>
              ))}
            </ul>
          </>
        )}
        {t.receipts?.length > 0 && (
          <>
            <h4>Money received</h4>
            <ul className="approval-history">
              {t.receipts.map((r) => (
                <li key={r.id}><span className="pill pill-a-approved">in</span> +{money(r.amount)} from {r.payer} · {r.memo} · {r.recorded_by.replace('human:', '')}</li>
              ))}
            </ul>
          </>
        )}
      </details>
    </div>
  )
}
