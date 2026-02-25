'use client'

import React, { useEffect, useState } from 'react'

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

export default function DecisionRisk() {
  const [rangeRow, setRangeRow] = useState<RangeRow | null>(null)
  const [risk, setRisk] = useState<RiskData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      try {
        const base = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
        const [rangesRes, riskRes] = await Promise.all([
          fetch(`${base}/api/market/ranges`),
          fetch(`${base}/api/account/risk?mode=demo`),
        ])
        if (!rangesRes.ok || !riskRes.ok) {
          throw new Error('Błąd pobierania danych')
        }
        const rangesJson = await rangesRes.json()
        const riskJson = await riskRes.json()

        const focus = new Set(['WLFIEUR', 'BTCEUR'])
        const picked = (rangesJson.data || []).find((r: any) => focus.has(r.symbol)) || (rangesJson.data || [])[0] || null
        if (!cancelled) {
          setRangeRow(picked)
          setRisk(riskJson.data || null)
        }
      } catch (err) {
        if (!cancelled) setError('Nie udało się pobrać danych')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchData()
    const interval = setInterval(fetchData, 60000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  function actionLabel(row: RangeRow | null) {
    if (!row) return 'CZEKAJ'
    if (row.buy_action && String(row.buy_action).includes('KUP')) return 'KUP'
    if (row.sell_action && String(row.sell_action).includes('SPRZEDAJ')) return 'SPRZEDAJ'
    return 'CZEKAJ'
  }

  const action = actionLabel(rangeRow)

  return (
    <div className="terminal-card rounded-lg p-5 border border-rldc-dark-border neon-card">
      <h2 className="text-lg font-semibold text-slate-200 mb-4">Decyzje & Ryzyko</h2>

      {loading && <div className="text-sm text-slate-400">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary">{error}</div>}

      {rangeRow && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-500">Para</div>
            <div className="text-sm font-semibold text-slate-200 font-mono">{rangeRow.symbol}</div>
          </div>

          <div className="rounded-lg border border-rldc-dark-border bg-rldc-dark-bg p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Co robić teraz</div>
            <div className={`text-2xl font-bold ${
              action === 'KUP' ? 'text-rldc-green-primary' : action === 'SPRZEDAJ' ? 'text-rldc-red-primary' : 'text-slate-200'
            }`}>
              {action}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-lg border border-rldc-dark-border bg-rldc-dark-bg p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Zakres kupna</div>
              <div className="font-mono text-slate-200">
                {rangeRow.buy_low ?? '--'} – {rangeRow.buy_high ?? '--'}
              </div>
              <div className="mt-1 text-slate-500">Cel zysku: <span className="font-mono text-slate-200">{rangeRow.buy_target ?? '--'}</span></div>
            </div>
            <div className="rounded-lg border border-rldc-dark-border bg-rldc-dark-bg p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Zakres sprzedaży</div>
              <div className="font-mono text-slate-200">
                {rangeRow.sell_low ?? '--'} – {rangeRow.sell_high ?? '--'}
              </div>
              <div className="mt-1 text-slate-500">Cel zysku: <span className="font-mono text-slate-200">{rangeRow.sell_target ?? '--'}</span></div>
            </div>
          </div>

          {rangeRow.comment && (
            <div className="text-xs text-slate-400 leading-relaxed">
              {rangeRow.comment}
            </div>
          )}
        </div>
      )}

      <div className="mt-4 pt-4 border-t border-rldc-dark-border">
        <div className="text-xs text-slate-500 mb-2">Limity ryzyka</div>
        {risk ? (
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Maks. dzienna strata</span>
              <span className="text-slate-200 font-mono">{risk.max_daily_loss_pct}%</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Maks. drawdown</span>
              <span className="text-slate-200 font-mono">{risk.max_drawdown_pct}%</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Najgorszy DD</span>
              <span className="text-slate-200 font-mono">{risk.worst_drawdown_pct}%</span>
            </div>
          </div>
        ) : (
          <div className="text-sm text-slate-400">Brak danych ryzyka</div>
        )}
      </div>
    </div>
  )
}
