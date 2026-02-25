'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { API_BASE, withAdminToken } from '../../lib/api'

type RangeRow = {
  symbol: string
  buy_low?: number
  buy_high?: number
  sell_low?: number
  sell_high?: number
  buy_action?: string
  buy_target?: number
  sell_action?: string
  sell_target?: number
  comment?: string
  timestamp?: string
}

type RiskData = {
  initial_balance: number
  max_daily_loss_pct: number
  max_drawdown_pct: number
  unrealized_pnl: number
  daily_loss_limit: number
  worst_drawdown_pct: number
  daily_loss_triggered: boolean
  drawdown_triggered: boolean
  positions_count: number
}

type PendingRow = {
  id: number
  symbol: string
  side: string
  quantity: number
  price?: number
  status: string
  created_at?: string
}

function normalizeSymbol(s: string): string {
  return (s || '').trim().replaceAll('/', '').replaceAll('-', '').toUpperCase()
}

function toNum(value: any): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function formatPrice(v: number | null): string {
  if (v === null) return '--'
  if (v < 1) return v.toFixed(6)
  if (v < 1000) return v.toFixed(4)
  return v.toFixed(2)
}

function actionLabel(row: RangeRow | null) {
  if (!row) return 'WAIT'
  if (row.buy_action && String(row.buy_action).includes('KUP')) return 'BUY'
  if (row.sell_action && String(row.sell_action).includes('SPRZEDAJ')) return 'SELL'
  return 'WAIT'
}

export default function DecisionsRiskPanel({
  mode,
  symbol,
}: {
  mode: 'demo' | 'live'
  symbol: string
}) {
  const sym = useMemo(() => normalizeSymbol(symbol), [symbol])

  const [rangeRow, setRangeRow] = useState<RangeRow | null>(null)
  const [risk, setRisk] = useState<RiskData | null>(null)
  const [control, setControl] = useState<any | null>(null)
  const [pending, setPending] = useState<PendingRow[]>([])
  const [pendingCount, setPendingCount] = useState<number | null>(null)
  const [tickerPrice, setTickerPrice] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [pendingRefreshing, setPendingRefreshing] = useState(false)
  const [ticketSide, setTicketSide] = useState<'BUY' | 'SELL'>('BUY')
  const [ticketQty, setTicketQty] = useState<string>('0.01')
  const [ticketReason, setTicketReason] = useState<string>('')
  const [ticketStatus, setTicketStatus] = useState<string | null>(null)

  const reloadPending = async () => {
    if (mode !== 'demo') return
    setPendingRefreshing(true)
    try {
      const res = await fetch(`${API_BASE}/api/orders/pending?mode=demo&status=PENDING&limit=5&include_total=true`)
      if (!res.ok) throw new Error('Błąd pobierania pending')
      const json = await res.json()
      setPending((json?.data || []) as PendingRow[])
      const total = typeof json?.total === 'number' ? json.total : typeof json?.count === 'number' ? json.count : null
      setPendingCount(total)
    } catch (e: any) {
      setPendingAction(String(e?.message || 'Błąd odświeżenia pending'))
    } finally {
      setPendingRefreshing(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const tasks: Promise<Response>[] = [
          fetch(`${API_BASE}/api/market/ranges`),
          fetch(`${API_BASE}/api/account/risk?mode=${mode}`),
        ]
        if (mode === 'demo') {
          tasks.push(fetch(`${API_BASE}/api/control/state`))
          tasks.push(fetch(`${API_BASE}/api/orders/pending?mode=demo&status=PENDING&limit=5`))
          tasks.push(fetch(`${API_BASE}/api/orders/pending?mode=demo&status=PENDING&limit=1&include_total=true`))
        }
        tasks.push(fetch(`${API_BASE}/api/market/ticker/${sym}`))
        const res = await Promise.all(tasks)
        if (res.slice(0, mode === 'demo' ? 5 : 2).some((r) => !r.ok)) throw new Error('Błąd pobierania danych')

        const rangesJson = await res[0].json()
        const riskJson = await res[1].json()

        const allRanges = (rangesJson.data || []) as any[]
        const picked =
          allRanges.find((r) => normalizeSymbol(String(r.symbol || '')) === sym) ||
          allRanges[0] ||
          null

        let controlJson: any = null
        let pendingJson: any = null
        let pendingCountJson: any = null
        let tickerJson: any = null
        if (mode === 'demo') {
          controlJson = await res[2].json()
          pendingJson = await res[3].json()
          pendingCountJson = await res[4].json()
          tickerJson = await res[5].json()
        } else {
          tickerJson = await res[2].json()
        }

        if (!cancelled) {
          setRangeRow(picked)
          setRisk(riskJson.data || null)
          setControl(controlJson?.data || null)
          setPending((pendingJson?.data || []) as PendingRow[])
          setPendingCount(typeof pendingCountJson?.total === 'number' ? pendingCountJson.total : typeof pendingCountJson?.count === 'number' ? pendingCountJson.count : null)
          setTickerPrice(toNum(tickerJson?.price))
        }
      } catch (e: any) {
        if (!cancelled) setError(String(e?.message || 'Nie udało się pobrać danych'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const interval = setInterval(load, 15000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [mode, sym])

  const action = actionLabel(rangeRow)

  const tradingEnabled = control?.demo_trading_enabled
  const tradingPill =
    mode === 'demo' ? (
      <div
        className={`px-2 py-1 rounded text-[10px] font-semibold border ${
          tradingEnabled === true
            ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
            : tradingEnabled === false
              ? 'bg-rldc-red-primary/15 text-rldc-red-primary border-rldc-red-primary/20'
              : 'bg-slate-500/10 text-slate-300 border-rldc-dark-border'
        }`}
        title="Control Plane"
      >
        TRADING: {tradingEnabled === null || tradingEnabled === undefined ? '--' : tradingEnabled ? 'ON' : 'OFF'}
      </div>
    ) : null

  const actPending = async (id: number, action: 'confirm' | 'reject' | 'cancel') => {
    const label = action === 'confirm' ? 'Confirm' : action === 'reject' ? 'Reject' : 'Cancel'
    setPendingAction(`${label} #${id}...`)
    try {
      const headers: Record<string, string> = withAdminToken()
      const res = await fetch(`${API_BASE}/api/orders/pending/${id}/${action}`, { method: 'POST', headers })
      if (!res.ok) throw new Error(res.status === 401 ? '401 Unauthorized (ADMIN_TOKEN?)' : 'Błąd akcji')
      setPendingAction('OK')
      // optimistic refresh: remove from list
      setPending((items) => items.filter((p) => Number(p.id) !== Number(id)))
      setPendingCount((c) => (typeof c === 'number' ? Math.max(0, c - 1) : c))
      await reloadPending()
    } catch (e: any) {
      setPendingAction(String(e?.message || 'Błąd akcji'))
    }
  }

  const bulkAct = async (action: 'confirm' | 'reject' | 'cancel') => {
    if (!pending.length) return
    setPendingAction(`${action.toUpperCase()} all (${pending.length})...`)
    for (const row of pending) {
      try {
        const headers: Record<string, string> = withAdminToken()
        const res = await fetch(`${API_BASE}/api/orders/pending/${Number(row.id)}/${action}`, { method: 'POST', headers })
        if (!res.ok) throw new Error(res.status === 401 ? '401 Unauthorized (ADMIN_TOKEN?)' : 'Błąd akcji')
      } catch (e: any) {
        setPendingAction(String(e?.message || 'Błąd akcji'))
        await reloadPending()
        return
      }
    }
    setPendingAction('OK')
    await reloadPending()
  }

  const submitTicket = async () => {
    setTicketStatus('Tworzę pending...')
    try {
      const qty = toNum(ticketQty)
      if (qty === null || qty <= 0) {
        setTicketStatus('Podaj poprawne qty > 0')
        return
      }
      const headers: Record<string, string> = withAdminToken({ 'Content-Type': 'application/json' })
      const res = await fetch(`${API_BASE}/api/orders/pending?mode=demo`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          symbol: sym,
          side: ticketSide,
          quantity: qty,
          price: tickerPrice,
          reason: ticketReason || undefined,
        }),
      })
      if (!res.ok) throw new Error(res.status === 401 ? '401 Unauthorized (ADMIN_TOKEN?)' : 'Błąd tworzenia pending')
      const json = await res.json()
      const row = json?.data as PendingRow | undefined
      if (row && row.id) {
        setPending((items) => [row, ...items].slice(0, 5))
        setPendingCount((c) => (typeof c === 'number' ? c + 1 : c))
      }
      setTicketStatus('OK')
      setTicketReason('')
      await reloadPending()
    } catch (e: any) {
      setTicketStatus(String(e?.message || 'Błąd tworzenia pending'))
    }
  }

  return (
    <div className="terminal-card rounded-lg p-5 border border-rldc-dark-border neon-card">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Decisions & Risk</div>
          <div className="mt-1 text-sm font-semibold text-slate-200 font-mono">{sym || '--'}</div>
        </div>
        <div className="flex items-center gap-2">
          {tradingPill}
          {mode === 'demo' && (
            <div className="px-2 py-1 rounded text-[10px] font-semibold border bg-rldc-dark-bg text-slate-200 border-rldc-dark-border">
              PENDING: {pendingCount === null ? '--' : pendingCount}
            </div>
          )}
        </div>
      </div>

      {loading && <div className="text-sm text-slate-400">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary">{error}</div>}

      <div className="space-y-4">
        <div className="rounded-lg border border-rldc-dark-border bg-rldc-dark-bg p-3">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Action</div>
          <div
            className={`text-3xl font-bold ${
              action === 'BUY'
                ? 'text-rldc-green-primary'
                : action === 'SELL'
                  ? 'text-rldc-red-primary'
                  : 'text-slate-200'
            }`}
          >
            {action}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">BUY range</div>
              <div className="font-mono text-slate-200">
                {rangeRow?.buy_low ?? '--'} – {rangeRow?.buy_high ?? '--'}
              </div>
              <div className="mt-1 text-slate-500">
                Target: <span className="font-mono text-slate-200">{rangeRow?.buy_target ?? '--'}</span>
              </div>
            </div>
            <div className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">SELL range</div>
              <div className="font-mono text-slate-200">
                {rangeRow?.sell_low ?? '--'} – {rangeRow?.sell_high ?? '--'}
              </div>
              <div className="mt-1 text-slate-500">
                Target: <span className="font-mono text-slate-200">{rangeRow?.sell_target ?? '--'}</span>
              </div>
            </div>
          </div>
          {rangeRow?.comment && <div className="mt-2 text-xs text-slate-400">{String(rangeRow.comment).slice(0, 180)}</div>}
        </div>

        <div className="rounded-lg border border-rldc-dark-border bg-rldc-dark-bg p-3">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Risk</div>
          {risk ? (
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
                <div className="text-slate-500">Daily loss limit</div>
                <div className="mt-1 font-mono text-slate-200">{risk.daily_loss_limit}</div>
                <div className={`mt-1 text-[10px] ${risk.daily_loss_triggered ? 'text-rldc-red-primary' : 'text-rldc-green-primary'}`}>
                  {risk.daily_loss_triggered ? 'TRIGGERED' : 'OK'}
                </div>
              </div>
              <div className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
                <div className="text-slate-500">Worst DD</div>
                <div className="mt-1 font-mono text-slate-200">{risk.worst_drawdown_pct}%</div>
                <div className={`mt-1 text-[10px] ${risk.drawdown_triggered ? 'text-rldc-red-primary' : 'text-rldc-green-primary'}`}>
                  {risk.drawdown_triggered ? 'TRIGGERED' : 'OK'}
                </div>
              </div>
              <div className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
                <div className="text-slate-500">Open positions</div>
                <div className="mt-1 font-mono text-slate-200">{risk.positions_count}</div>
              </div>
              <div className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
                <div className="text-slate-500">Unrealized</div>
                <div className="mt-1 font-mono text-slate-200">{risk.unrealized_pnl}</div>
              </div>
            </div>
          ) : (
            <div className="text-xs text-slate-500">--</div>
          )}
        </div>

        {mode === 'demo' && (
          <div className="rounded-lg border border-rldc-dark-border bg-rldc-dark-bg p-3">
            <div className="flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Pending (DEMO)</div>
              <div className="flex items-center gap-2">
                {pendingRefreshing && <div className="text-[10px] text-slate-500">refresh...</div>}
                <button
                  onClick={() => reloadPending()}
                  className="px-2 py-1 text-[10px] rounded border border-rldc-dark-border bg-slate-500/10 text-slate-200 hover:bg-slate-500/20 transition"
                >
                  Refresh
                </button>
                {pending.length > 0 && (
                  <>
                    <button
                      onClick={() => bulkAct('confirm')}
                      className="px-2 py-1 text-[10px] rounded bg-rldc-green-primary/15 text-rldc-green-primary border border-rldc-green-primary/20 hover:bg-rldc-green-primary hover:text-white transition"
                    >
                      Confirm all
                    </button>
                    <button
                      onClick={() => bulkAct('cancel')}
                      className="px-2 py-1 text-[10px] rounded bg-slate-500/10 text-slate-200 border border-rldc-dark-border hover:bg-slate-600 hover:text-white transition"
                    >
                      Cancel all
                    </button>
                    <button
                      onClick={() => bulkAct('reject')}
                      className="px-2 py-1 text-[10px] rounded bg-rldc-red-primary/15 text-rldc-red-primary border border-rldc-red-primary/20 hover:bg-rldc-red-primary hover:text-white transition"
                    >
                      Reject all
                    </button>
                  </>
                )}
                {pendingAction && <div className="text-[10px] text-slate-500">{pendingAction}</div>}
              </div>
            </div>
            <div className="mt-3 space-y-2">
              {!pending.length && <div className="text-xs text-slate-500">Brak pending.</div>}
              {pending.map((p) => (
                <div key={p.id} className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs font-mono text-slate-200">
                      #{p.id} {p.side} {p.symbol} qty={p.quantity}
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => actPending(Number(p.id), 'confirm')}
                        className="px-2 py-1 text-[10px] rounded bg-rldc-green-primary/20 text-rldc-green-primary hover:bg-rldc-green-primary/30 transition"
                      >
                        Confirm
                      </button>
                      <button
                        onClick={() => actPending(Number(p.id), 'reject')}
                        className="px-2 py-1 text-[10px] rounded bg-rldc-red-primary/20 text-rldc-red-primary hover:bg-rldc-red-primary/30 transition"
                      >
                        Reject
                      </button>
                      <button
                        onClick={() => actPending(Number(p.id), 'cancel')}
                        className="px-2 py-1 text-[10px] rounded bg-slate-500/10 text-slate-200 hover:bg-slate-500/20 transition border border-rldc-dark-border"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                  <div className="mt-1 text-[10px] text-slate-500">
                    status={p.status} • created={p.created_at || '--'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {mode === 'demo' && (
          <div className="rounded-lg border border-rldc-dark-border bg-rldc-dark-bg p-3">
            <div className="flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Trade ticket (DEMO)</div>
              {ticketStatus && <div className="text-[10px] text-slate-500">{ticketStatus}</div>}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Side</div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setTicketSide('BUY')}
                    className={`px-3 py-2 text-xs rounded border transition ${
                      ticketSide === 'BUY'
                        ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
                        : 'bg-rldc-dark-bg text-slate-300 border-rldc-dark-border hover:bg-rldc-dark-hover'
                    }`}
                  >
                    BUY
                  </button>
                  <button
                    onClick={() => setTicketSide('SELL')}
                    className={`px-3 py-2 text-xs rounded border transition ${
                      ticketSide === 'SELL'
                        ? 'bg-rldc-red-primary/15 text-rldc-red-primary border-rldc-red-primary/20'
                        : 'bg-rldc-dark-bg text-slate-300 border-rldc-dark-border hover:bg-rldc-dark-hover'
                    }`}
                  >
                    SELL
                  </button>
                </div>
              </div>
              <div className="rounded-lg border border-rldc-dark-border bg-[#0b121a] p-3">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Qty</div>
                <input
                  value={ticketQty}
                  onChange={(e) => setTicketQty(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 font-mono"
                  placeholder="0.01"
                />
                <div className="mt-2 text-[10px] text-slate-500">
                  Price: <span className="font-mono text-slate-200">{formatPrice(tickerPrice)}</span>
                </div>
              </div>
            </div>
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Reason (optional)</div>
              <input
                value={ticketReason}
                onChange={(e) => setTicketReason(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200"
                placeholder="Manual trade"
              />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={submitTicket}
                className="px-4 py-2 text-xs rounded bg-rldc-teal-primary/20 text-rldc-teal-primary hover:bg-rldc-teal-primary/30 transition"
              >
                Create pending
              </button>
              <div className="text-[10px] text-slate-500">Creates PENDING; use Confirm/Reject above.</div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
