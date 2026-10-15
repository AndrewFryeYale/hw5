import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Approval, Cash, DeskEvent, TicketDetail, TicketSummary } from './api'
import { API_URL, api } from './api'
import { ApprovalCheck } from './components/ApprovalCheck'
import { TicketPanel } from './components/TicketPanel'
import { TicketQueue } from './components/TicketQueue'
import { TopBar } from './components/TopBar'
import { deskActions, latestRun } from './derive'

const FAST_POLL = 1200 // while agents are working
const SLOW_POLL = 4000

function hashTicket(): number | null {
  const m = location.hash.match(/^#(\d+)$/)
  return m ? Number(m[1]) : null
}

function loadSigner() {
  try { return localStorage.getItem('desk.signer') ?? '' } catch { return '' }
}

export default function App() {
  const [online, setOnline] = useState(true)
  const [tickets, setTickets] = useState<TicketSummary[]>([])
  const [cash, setCash] = useState<Cash | null>(null)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(hashTicket) // #103 deep-links a ticket
  const [detail, setDetail] = useState<TicketDetail | null>(null)
  const [events, setEvents] = useState<Record<number, DeskEvent[]>>({})
  const [lastResetSeq, setLastResetSeq] = useState(0)
  const [signer, setSigner] = useState(loadSigner)
  const [starting, setStarting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [kick, setKick] = useState(0) // bump to poll immediately after an action

  const seqs = useRef<Record<number, number>>({})
  const anyRunning = tickets.some((t) => t.agent_running)

  const poll = useCallback(async () => {
    try {
      const [t, c, a] = await Promise.all([api.tickets(), api.cash(), api.approvals()])
      setTickets(t.tickets)
      setCash(c)
      setApprovals(a.approvals)
      setSelectedId((cur) => cur ?? t.tickets.find((x) => x.state === 'open')?.id ?? t.tickets[0]?.id ?? null)
      setOnline(true)
    } catch {
      setOnline(false)
    }
  }, [])

  const pollTicket = useCallback(async (id: number) => {
    try {
      const [d, ev] = await Promise.all([api.ticket(id), api.events(id, seqs.current[id] ?? 0)])
      setDetail((cur) => (cur && cur.id !== id ? cur : d))
      setLastResetSeq(ev.last_reset_seq)
      if (ev.events.length) {
        seqs.current[id] = ev.events[ev.events.length - 1].seq
        // Merge by seq: overlapping polls (e.g. React StrictMode's double effect) must not duplicate events.
        setEvents((cur) => {
          const bySeq = new Map((cur[id] ?? []).map((e) => [e.seq, e]))
          for (const e of ev.events) bySeq.set(e.seq, e)
          return { ...cur, [id]: [...bySeq.values()].sort((a, b) => a.seq - b.seq) }
        })
      }
    } catch {
      /* the main poll reports offline */
    }
  }, [])

  // One polling loop: fast while anyone is working, slow otherwise.
  useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const loop = async () => {
      await poll()
      if (selectedId != null) await pollTicket(selectedId)
      if (!stop) timer = setTimeout(loop, anyRunning ? FAST_POLL : SLOW_POLL)
    }
    loop()
    return () => { stop = true; clearTimeout(timer) }
  }, [poll, pollTicket, selectedId, anyRunning, kick])

  useEffect(() => {
    if (selectedId != null && location.hash !== `#${selectedId}`) history.replaceState(null, '', `#${selectedId}`)
  }, [selectedId])

  useEffect(() => {
    try { localStorage.setItem('desk.signer', signer) } catch { /* private mode */ }
  }, [signer])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 4500)
    return () => clearTimeout(t)
  }, [toast])

  const ticketEvents = useMemo(() => (selectedId != null ? events[selectedId] ?? [] : []), [events, selectedId])
  const run = useMemo(() => latestRun(ticketEvents, lastResetSeq), [ticketEvents, lastResetSeq])
  const feedEvents = useMemo(() => {
    const human = deskActions(ticketEvents, lastResetSeq)
    return [...(run?.events ?? []), ...human].sort((a, b) => a.seq - b.seq)
  }, [run, ticketEvents, lastResetSeq])
  const pendingByTicket = useMemo(() => {
    const m: Record<number, number> = {}
    for (const a of approvals) if (a.ticket_id != null) m[a.ticket_id] = (m[a.ticket_id] ?? 0) + 1
    return m
  }, [approvals])

  const who = signer.trim() || 'desk'

  async function start() {
    if (selectedId == null) return
    setStarting(true)
    try {
      await api.runTicket(selectedId)
      setToast(`The team is on ticket #${selectedId}.`)
    } catch (e) {
      setToast((e as Error).message)
    } finally {
      setStarting(false)
      setKick((k) => k + 1)
    }
  }

  return (
    <div className="app">
      <TopBar
        cash={cash}
        signer={signer}
        onSigner={setSigner}
        online={online}
        onReset={async () => {
          await api.reset()
          setDetail(null)
          setToast('Fresh start: the shop data is back to the original.')
          setKick((k) => k + 1)
        }}
      />

      {!online && (
        <div className="offline">
          Can't reach the desk API at <code>{API_URL}</code>. Start it with
          <code>cd backend &amp;&amp; uvicorn main:app --reload --port 8000</code>
        </div>
      )}

      <div className="layout">
        <TicketQueue tickets={tickets} selectedId={selectedId} pending={pendingByTicket}
                     onSelect={(id) => { setSelectedId(id); setDetail(null) }} />

        <main className="main">
          {detail && detail.id === selectedId ? (
            <TicketPanel
              ticket={detail}
              run={run}
              feedEvents={feedEvents}
              pendingHere={pendingByTicket[detail.id] ?? 0}
              starting={starting}
              onStart={start}
              onReceipt={async (amount, memo) => {
                await api.recordReceipt({ amount, memo, payer: detail.requester, received_by: who, ticket_id: detail.id })
                setToast(`Recorded $${amount.toFixed(2)} from ${detail.requester}.`)
                setKick((k) => k + 1)
              }}
              onResolve={async (note) => {
                await api.resolveTicket(detail.id, who, note)
                setToast(`Ticket #${detail.id} is resolved.`)
                setKick((k) => k + 1)
              }}
            />
          ) : (
            <div className="panel-skeleton">{online ? 'Opening ticket…' : ''}</div>
          )}
        </main>

        <aside className="tray" aria-label="Approvals waiting for a signature">
          <div className="tray-head">
            <h2>Signature tray</h2>
            <span className="queue-count">{approvals.length ? `${approvals.length} waiting` : 'all clear'}</span>
          </div>
          <p className="tray-note">The agents can only ask. Nothing is paid or ordered until a person signs.</p>
          {approvals.length === 0 ? (
            <div className="tray-empty">
              <div className="tray-empty-icon" aria-hidden>✍️</div>
              Nothing to sign right now.
            </div>
          ) : (
            approvals.map((a) => (
              <ApprovalCheck
                key={a.id}
                approval={a}
                defaultSigner={signer.trim()}
                onApprove={async (id, name) => {
                  await api.approve(id, name)
                  setToast(`Approval #${id} signed by ${name}.`)
                  setTimeout(() => setKick((k) => k + 1), 1400) // let the stamp land before the check leaves
                }}
                onReject={async (id, name) => {
                  await api.reject(id, name)
                  setToast(`Approval #${id} voided.`)
                  setTimeout(() => setKick((k) => k + 1), 1400)
                }}
              />
            ))
          )}
        </aside>
      </div>

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  )
}
