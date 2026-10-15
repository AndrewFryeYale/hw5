import { useEffect, useRef, useState } from 'react'
import type { Cash } from '../api'
import { money } from '../derive'

/** Counts smoothly from the old balance to the new one so a payment is felt, not just shown. */
function useTween(target: number | undefined, ms = 900) {
  const [shown, setShown] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    if (target == null) return
    const start = from.current ?? target
    if (start === target) { setShown(target); return }
    const t0 = performance.now()
    let raf = 0
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / ms)
      const eased = 1 - Math.pow(1 - p, 3)
      setShown(start + (target - start) * eased)
      if (p < 1) raf = requestAnimationFrame(step)
      else from.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return shown
}

interface Props {
  cash: Cash | null
  signer: string
  onSigner: (name: string) => void
  onReset: () => Promise<void>
  online: boolean
}

export function TopBar({ cash, signer, onSigner, onReset, online }: Props) {
  const balance = useTween(cash?.balance)
  const [confirming, setConfirming] = useState(false)
  const [resetting, setResetting] = useState(false)
  const low = cash != null && cash.balance < 500
  const after = cash ? cash.balance - cash.pending_approvals_total : undefined
  // Rent just past the 30-day window isn't in "owed soon", but it's the next big bill.
  const nextRent = cash?.upcoming_rent?.find((r) => !r.counted_in_obligations)

  useEffect(() => {
    if (!confirming) return
    const t = setTimeout(() => setConfirming(false), 4000)
    return () => clearTimeout(t)
  }, [confirming])

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" aria-hidden>
          <svg viewBox="0 0 64 64"><ellipse cx="32" cy="38" rx="22" ry="13" /><circle cx="32" cy="18" r="7" /></svg>
        </div>
        <div>
          <div className="brand-name">Campus Customs <span>Desk</span></div>
          <div className="brand-sub">
            <span className={`status-dot ${online ? 'on' : 'off'}`} />
            {online ? `Shop date ${cash?.shop_date ?? '…'}` : 'Desk API offline'}
          </div>
        </div>
      </div>

      <div className={`drawer ${low ? 'drawer-low' : ''}`} aria-live="polite">
        <div className="drawer-label">Checking balance</div>
        <div className="drawer-balance">{balance != null ? money(balance) : '—'}</div>
        <div className="drawer-sub">
          {cash && cash.pending_approvals_total > 0 ? (
            <>
              <span className="drawer-pending">−{money(cash.pending_approvals_total)} awaiting your signature</span>
              <span> → {money(after!)}</span>
            </>
          ) : cash ? (
            <span title={cash.warnings?.[0]}>
              {low ? 'Low cash: under $500' : `Owed soon: ${money(cash.total_obligations)}`}
              {nextRent && <> · next rent {money(nextRent.amount)} on {nextRent.next_due.slice(5).replace('-', '/')}</>}
            </span>
          ) : null}
        </div>
      </div>

      <div className="topbar-right">
        <label className="signer">
          <span>At the desk</span>
          <input value={signer} onChange={(e) => onSigner(e.target.value)} placeholder="Your name" />
        </label>
        <button
          className={`btn ${confirming ? 'btn-danger' : 'btn-ghost'}`}
          disabled={resetting || !online}
          onClick={async () => {
            if (!confirming) { setConfirming(true); return }
            setResetting(true)
            try { await onReset() } finally { setResetting(false); setConfirming(false) }
          }}
        >
          {resetting ? 'Resetting…' : confirming ? 'Click again to wipe & reset' : 'Fresh start'}
        </button>
      </div>
    </header>
  )
}
