import type { TicketSummary } from '../api'
import { STATUS_LABEL, TICKET_TYPE } from '../agents'

interface Props {
  tickets: TicketSummary[]
  selectedId: number | null
  pending: Record<number, number>
  onSelect: (id: number) => void
}

export function TicketQueue({ tickets, selectedId, pending, onSelect }: Props) {
  const open = tickets.filter((t) => t.state === 'open').length
  return (
    <nav className="queue" aria-label="Tickets">
      <div className="queue-head">
        <h2>Ticket queue</h2>
        <span className="queue-count">{open} open · {tickets.length - open} resolved</span>
      </div>
      <ul>
        {tickets.map((t) => {
          const type = TICKET_TYPE[t.type] ?? { label: t.type, icon: '📄' }
          return (
            <li key={t.id}>
              <button
                className={`ticket-card ${t.id === selectedId ? 'selected' : ''} ${t.state === 'resolved' ? 'resolved' : ''}`}
                onClick={() => onSelect(t.id)}
                aria-current={t.id === selectedId}
              >
                <span className="ticket-icon" aria-hidden>{type.icon}</span>
                <span className="ticket-body">
                  <span className="ticket-top">
                    <span className="ticket-id">#{t.id}</span>
                    <span className="ticket-type">{type.label}</span>
                  </span>
                  <span className="ticket-subject">{t.subject}</span>
                  <span className="ticket-requester">{t.requester}</span>
                  <span className="ticket-tags">
                    {t.agent_running ? (
                      <span className="pill pill-live"><i className="dot" /> Team working</span>
                    ) : (
                      <span className={`pill pill-${t.status}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
                    )}
                    {pending[t.id] ? <span className="pill pill-sign">✍ {pending[t.id]} to sign</span> : null}
                  </span>
                </span>
                {t.state === 'resolved' && <span className="mini-stamp">Resolved</span>}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
