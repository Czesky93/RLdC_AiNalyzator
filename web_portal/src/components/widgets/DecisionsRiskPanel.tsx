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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)

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
          tasks.push(fetch(`${API_BASE}/api/orders/pending?mode=demo&status=PENDING&limit=200`))
        }
        const res = await Promise.all(tasks)
        if (res.some((r) => !r.ok)) throw new Error('Błąd pobierania danych')

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
        if (mode === 'demo') {
          controlJson = await res[2].json()
          pendingJson = await res[3].json()
          pendingCountJson = await res[4].json()
        }

        if (!cancelled) {
          setRangeRow(picked)
          setRisk(riskJson.data || null)
          setControl(controlJson?.data || null)
          setPending((pendingJson?.data || []) as PendingRow[])
          setPendingCount(typeof pendingCountJson?.count === 'number' ? pendingCountJson.count : null)
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

  const actPending = async (id: number, action: 'confirm' | 'reject') => {
    setPendingAction(`${action === 'confirm' ? 'Confirm' : 'Reject'} #${id}...`)
    try {
      const headers: Record<string, string> = withAdminToken()
      const res = await fetch(`${API_BASE}/api/orders/pending/${id}/${action}`, { method: 'POST', headers })
      if (!res.ok) throw new Error(res.status === 401 ? '401 Unauthorized (ADMIN_TOKEN?)' : 'Błąd akcji')
      setPendingAction('OK')
      // optimistic refresh: remove from list
      setPending((items) => items.filter((p) => Number(p.id) !== Number(id)))
      setPendingCount((c) => (typeof c === 'number' ? Math.max(0, c - 1) : c))
    } catch (e: any) {
      setPendingAction(String(e?.message || 'Błąd akcji'))
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
              {pendingAction && <div className="text-[10px] text-slate-500">{pendingAction}</div>}
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
      </div>
    </div>
  )
}

