// An approval request drawn as a bank check. Money only moves when a person signs it: typing your name on
// the signature line enables "Sign & approve". Rejecting voids the check. Both call the desk API.

import { useState } from 'react'
import type { Approval } from '../api'
import { checkWords, money } from '../derive'

function payee(a: Approval) {
  if (a.kind === 'rent') return `Landlord, lease #${a.ref_id}`
  if (a.kind === 'invoice') return `Vendor invoice #${a.ref_id}`
  return `Vendor #${a.ref_id} (purchase order)`
}

function memo(a: Approval) {
  if (a.kind === 'purchase') return `${a.qty} × ${a.sku} ${a.size}`
  return a.kind === 'rent' ? 'Monthly rent' : 'Vendor bill'
}

interface Props {
  approval: Approval
  defaultSigner: string
  onApprove: (id: number, signer: string) => Promise<void>
  onReject: (id: number, signer: string) => Promise<void>
}

export function ApprovalCheck({ approval: a, defaultSigner, onApprove, onReject }: Props) {
  const [signature, setSignature] = useState('')
  const [stamp, setStamp] = useState<'paid' | 'void' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const signer = signature.trim()

  async function act(kind: 'paid' | 'void') {
    setBusy(true)
    setError(null)
    try {
      if (kind === 'paid') await onApprove(a.id, signer)
      else await onReject(a.id, signer || defaultSigner || 'desk')
      setStamp(kind)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className={`check ${stamp ? 'check-done' : ''}`}>
      <header className="check-top">
        <div>
          <div className="check-bank">Campus Customs · Checking</div>
          <div className="check-meta">Ticket #{a.ticket_id ?? '—'} · requested by {a.requested_by}</div>
        </div>
        <div className="check-no">
          No. {String(a.id).padStart(4, '0')}
          <span>{a.created_at}</span>
        </div>
      </header>

      <div className="check-line">
        <span className="check-label">Pay to the order of</span>
        <span className="check-payee">{payee(a)}</span>
        <span className="check-amount">{money(a.amount)}</span>
      </div>
      <div className="check-words">{checkWords(a.amount)} dollars</div>

      <div className="check-bottom">
        <div className="check-memo">
          <span className="check-label">Memo</span> {memo(a)}
          <p className="check-reason" title={a.reason}>{a.reason}</p>
        </div>
        <label className="check-sign">
          <input
            value={signature}
            onChange={(e) => setSignature(e.target.value)}
            placeholder={defaultSigner ? `Sign as ${defaultSigner}` : 'Sign your name'}
            disabled={busy || !!stamp}
            aria-label="Signature"
          />
          <span className="check-label">Authorized signature</span>
        </label>
      </div>

      {!stamp && (
        <div className="check-actions">
          <button className="btn btn-ghost" disabled={busy} onClick={() => act('void')}>Void</button>
          <button className="btn btn-primary" disabled={busy || !signer} onClick={() => act('paid')}
                  title={signer ? '' : 'Type your name on the signature line first'}>
            {busy ? 'Signing…' : 'Sign & approve'}
          </button>
        </div>
      )}
      {error && <p className="check-error">{error}</p>}
      {stamp && <div className={`stamp stamp-${stamp}`}>{stamp === 'paid' ? (a.kind === 'purchase' ? 'Ordered' : 'Paid') : 'Void'}</div>}
    </article>
  )
}
