# Campus Customs Desk: design choices

The dashboard lives in `frontend/` (React 19 + Vite + TypeScript, no UI library). It talks to the desk API at `http://localhost:8000` (set in `frontend/.env` as `VITE_API_URL`). The backend allows exactly the Vite origin, `http://localhost:5173` (`FRONTEND_ORIGINS` in `backend/main.py`), and Vite is pinned to that port with `strictPort`.

```
cd backend  && uvicorn main:app --reload --port 8000
cd frontend && npm install && npm run dev      # http://localhost:5173
```

## The idea: a desk, not an admin panel

The brief was "someone should want to sit at this desk." So the screen is modeled on a real shop desk. There's a cash drawer at the top, a stack of tickets on the left, a huddle table in the middle where the team talks, and a signature tray on the right where the checks wait for you. Every metaphor maps onto a real part of the system, so it explains the architecture without a diagram:

| On screen | In the system |
|---|---|
| Cash drawer (top bar) | `GET /cash`: `cash_accounts.balance`, plus what's waiting for a signature and the next rent |
| Ticket queue | `GET /tickets`: status, open/resolved, "Team working", "✍ 1 to sign" |
| The huddle (round table) | `GET /events`: live agent runs, delegations, MCP calls |
| Shop ledger (center of the table) | The `campus-customs` MCP server. Every lookup lands here |
| Signature tray / checks | `GET /approvals` + `POST /approvals/{id}/approve` or `/reject` |
| Debrief | A per-agent summary built from the same events once the run ends |
| Ticket log | `tickets.notes`, the approval history and money received |
| "＋ Record money received" | `POST /receipts`: a person adds a deposit or payment to checking |

## Unique design elements

### 1. The huddle: watching a multi-agent run as a meeting (the main one)
Most agent dashboards show a scrolling log. Here the five agents sit around an oval wooden table: the Boss at the head, the four specialists around it, each in their own color.
- **Who's working:** an idle seat is a faded dashed outline. The working agent fills with color, grows slightly, and pulses. A finished agent gets a green ✓.
- **What they're doing:** a speech bubble, translated from the tool name into plain speech. `check_stock` becomes "checking the shelves", `get_cash_position` becomes "checking the cash drawer", and a delegation becomes "waiting on Accounting".
- **Who handed work to whom:** each delegation is drawn as a thread from the caller's seat to the callee's, bowed toward the table. It animates while that teammate is working and fades to a dotted trace afterward. So when a run ends, the table literally shows the shape of the conversation: a single thread for a lean run, and a web when the Boss called everyone.
- **Where facts come from:** every MCP call drops a chip onto the shop ledger in the middle of the table, bordered in the caller's color. That reinforces the rule from Problem 5 that facts only come from the MCP server: if it didn't hit the ledger, the agent didn't look it up. Write tools (`request_approval`, `update_ticket`) land in brass so they stand out.

The point of this view is to make efficiency visible. Problem 6 said plans that send every specialist on every ticket should score low. Here you can see the over-calling, and the debrief scores it ("3/4 specialists called" turns amber).

### 2. Sign the check: approvals as real checks
Approval requests come in as bank checks: payee, amount in figures and in words ("Two thousand four hundred and 00/100 dollars"), memo, the Boss's reason, and a MICR-style line. **Sign & approve** stays disabled until you type your name on the signature line, which renders in a handwriting font. Approving thumps a PAID stamp onto the check (ORDERED for a purchase). Rejecting stamps it VOID.
- **Why:** this is the one moment in the system where real money moves, so it deserves friction and ceremony. Typing your name is a small, deliberate act: it's hard to approve by accident, and the name you sign goes into the payment record (`approved_by = human:<name>`) and the ticket log. People already know what signing a check means. No tooltip is needed to explain that the agents can only ask.

### 3. Ink stamps for status
A ticket that is resolved gets a green RESOLVED stamp that lands with a little overshoot, and the queue card gets a small rotated stamp. Stamps are how paper offices mark things done. They read at a glance from across the room, which a 12px status pill doesn't.

## Visual system

- **Palette:** paper and ink with Yale navy (`#0f2d52`) and a brass accent (`#b8892f`). Warm off-white paper instead of pure white lowers glare for someone at a desk all day. Navy ties the shop to its Yale merchandise. Brass is used only for money: the balance label, pending signatures, write tools. So gold always means "this touches cash."
- **One color per agent:** Boss navy, Inventory green, Accounting brass-gold, Customer Service plum, Facilities terracotta. Each color is used the same way everywhere (seat, thread, transcript name, debrief card stripe, ledger chip border). Learn it once and you can follow the whole run by color.
- **Type:**
  - Fraunces (a soft serif) for headings and the balance, so it reads like a ledger or letterhead.
  - Inter for UI text, for legibility.
  - JetBrains Mono for tool names and arguments: they're code, and it should look like code.
  - Homemade Apple only for signatures.
- **Hierarchy:** the selected ticket's title is the biggest text on the page, the balance is the second biggest, and everything else is quiet. A desk worker's two questions are "what am I working on?" and "how much money do we have?"
- **Status pills use the same color logic as the agents:**
  - Blue: open
  - Brass: needs approval (money)
  - Plum: waiting on customer, which is customer service's color
  - Red: escalated
  - Green: resolved

## Interaction choices

- **Background runs with polling.** `POST /tickets/{id}/run` returns at once, and the board polls every 1.2 s while any ticket is running and every 4 s when idle. Polling `/events?since=<seq>` only fetches new events. It's simpler and sturdier than websockets for a desk app, and events are merged by `seq`, so overlapping polls can never duplicate a line.
- **The transcript explains itself.** Each line is a sentence ("asked Accounting: …", "picked up the ticket"). Tool calls show as chips with their arguments. Guardrail rejections are amber, and human actions get a green background so you can tell people from agents.
- **Debrief after the run:** efficiency metrics (specialists called out of 4, handoffs, ledger lookups, tokens, time), the Boss's call with its final status, one card per agent that took part (tools used with counts, who they asked, what they reported), and the draft customer reply set as a lined letter labeled "a person reviews and sends it."
- **Finished agents' reports are hover-only on the table** (the debrief shows them in full). The table stays readable, and only live activity talks.
- **A human can close a ticket.** "Mark resolved" asks for a one-line reason, and is refused while agents are running or while a check is still unsigned. Agents correctly leave #101/#103 at `waiting_on_customer`, so a person has to close them when the customer actually picks up.
- **Two-step "Fresh start"** in the top bar: the first click arms it ("Click again to wipe & reset"), and it disarms after 4 s. Resetting is destructive, but you need it often enough during demos that a modal would be annoying.
- **Money in is a person's job too.** "＋ Record money received" on a ticket opens a two-field form (amount, memo), credited to that ticket's requester and signed with the desk name. It's the mirror of signing a check: money only moves in either direction when a person does it. The receipt shows in the ticket log, and the drawer's balance tweens up.
- **The drawer shows the next rent** even when it's past the 30-day "owed soon" window ("next rent $2,400.00 on 10/02"). After both bills are paid, $160.00 can look fine until you see that line.
- **"At the desk" name.** Typed once, remembered in localStorage, and suggested as the signer on every check.
- **The balance tweens** from old to new over about 0.9 s when a check is signed, so you feel the money leave the drawer. The drawer also previews the balance after pending approvals ("−$2,400.00 awaiting your signature → $1,000.00") and turns red under $500, matching the Boss's low-cash policy.
- **Deep links:** `http://localhost:5173/#103` opens ticket #103 directly.
- **Offline banner:** if the API isn't running, the board says so and shows the exact uvicorn command.

## Accessibility and responsiveness

- Real buttons and form fields throughout, `aria-current` on the selected ticket, `aria-live` on the balance, and `role="status"` toasts.
- Color is never the only signal. Every state also has text (pill labels, ✓ badges, "Team working", stamp words).
- `prefers-reduced-motion` turns off the pulses, threads and stamp animations.
- **Breakpoints:**
  - Three columns at 1280px and up.
  - The signature tray moves under the ticket below 1280px.
  - A single column below 860px.

## What I'd do next

- A dark "after hours" theme. This is light-only for now, to keep the paper metaphor consistent.
- Pushing events over SSE instead of polling.
- Sound on approval: a soft stamp thud.
- A run picker to replay older runs on the huddle table, like a meeting recording.
