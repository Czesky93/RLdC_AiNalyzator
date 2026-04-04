'use client'

import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getApiBase } from '../../lib/api'

interface Position {
  id: number
  symbol: string
  side: 'LONG' | 'SHORT'
  quantity: number
  entry_price: number
  current_price: number
  unrealized_pnl: number
  pnl_percent: number
  break_even_price?: number | null
  expected_net_profit?: number | null
  take_profit_price?: number | null
  stop_loss_price?: number | null
  plan_status?: string | null
  requires_revision?: boolean
  confidence_score?: number | null
}

export default function PositionsTable({ mode = 'demo' }: { mode?: 'demo' | 'live' }) {
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchPositions = async () => {
      try {
        const base = getApiBase()
        const res = await fetch(`${base}/api/positions?mode=${mode}`)
        if (res.ok) {
          const data = await res.json()
          if (!cancelled) setPositions(data.data || [])
        } else {
          if (!cancelled) setError('Błąd pobierania pozycji')
        }
      } catch (err) {
        if (!cancelled) setError('Nie udało się pobrać pozycji')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchPositions()
    const interval = setInterval(fetchPositions, 10000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [mode])

  const displayPositions = positions

  return (
    <div className="terminal-card rounded-lg p-4 border border-rldc-dark-border">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200">Otwarte Pozycje</h2>
        <div className="flex items-center space-x-2">
          <span className="text-[10px] uppercase tracking-widest text-teal-primary font-medium">
            {displayPositions.length} pozycji
          </span>
          <div className={`text-[10px] uppercase tracking-widest font-semibold ${mode === 'live' ? 'text-amber-400' : 'text-slate-500'}`}>
            {mode === 'live' ? 'LIVE' : 'DEMO'}
          </div>
        </div>
      </div>
      
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-[11px]">
          <thead>
            <tr className="border-b border-rldc-dark-border text-left text-[10px] uppercase tracking-widest text-slate-500">
              <th className="pb-3 font-medium">#</th>
              <th className="pb-3 font-medium">Symbol</th>
              <th className="pb-3 font-medium">Strona</th>
              <th className="pb-3 font-medium text-right">Ilość</th>
              <th className="pb-3 font-medium text-right">Cena kupna</th>
              <th className="pb-3 font-medium text-right">Cena teraz</th>
              <th className="pb-3 font-medium text-right">P&L</th>
              <th className="pb-3 font-medium text-right">Plan</th>
              <th className="pb-3 font-medium text-center">Akcje</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-slate-400">
                  Ładowanie pozycji...
                </td>
              </tr>
            ) : displayPositions.length === 0 ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-slate-400">
                  Brak otwartych pozycji
                </td>
              </tr>
            ) : (
              displayPositions.map((position, idx) => {
                const pnl = position.unrealized_pnl ?? 0
                const isPnlPositive = pnl >= 0
                const fmtPrice = (v: number) => v < 1 ? v.toFixed(6) : v < 1000 ? v.toFixed(4) : v.toFixed(2)
                return (
                  <tr key={position.id ?? idx} className="table-row">
                    <td className="py-2.5 text-slate-400">{idx + 1}</td>
                    <td className="py-2.5 text-slate-300 font-medium">{position.symbol}</td>
                    <td className="py-2.5">
                      <span className={`badge-${position.side === 'LONG' ? 'success' : 'danger'}`}>
                        {position.side === 'LONG' ? 'LONG' : 'SHORT'}
                      </span>
                    </td>
                    <td className="py-2.5 text-right text-slate-300">{position.quantity}</td>
                    <td className="py-2.5 text-right text-slate-400">{fmtPrice(position.entry_price)} EUR</td>
                    <td className="py-2.5 text-right text-slate-300">{fmtPrice(position.current_price)} EUR</td>
                    <td className={`py-2.5 text-right font-semibold ${isPnlPositive ? 'text-green-primary' : 'text-red-primary'}`}>
                      {isPnlPositive ? '+' : ''}{pnl.toFixed(4)} EUR
                      <span className="text-xs ml-1">({isPnlPositive ? '+' : ''}{position.pnl_percent.toFixed(2)}%)</span>
                    </td>
                    <td className="py-2.5 text-right text-[10px] leading-relaxed">
                      <div className="text-slate-300">{position.plan_status || 'brak planu'}</div>
                      <div className="text-slate-500">
                        BE: {position.break_even_price != null ? `${fmtPrice(position.break_even_price)} EUR` : '—'}
                      </div>
                      <div className="text-slate-500">
                        Net: {position.expected_net_profit != null ? `${position.expected_net_profit >= 0 ? '+' : ''}${position.expected_net_profit.toFixed(2)} EUR` : '—'}
                      </div>
                      {(position.take_profit_price != null || position.stop_loss_price != null) && (
                        <div className="text-slate-500">
                          TP {position.take_profit_price != null ? fmtPrice(position.take_profit_price) : '—'} / SL {position.stop_loss_price != null ? fmtPrice(position.stop_loss_price) : '—'}
                        </div>
                      )}
                      {position.requires_revision && (
                        <div className="text-amber-400">rewizja wymagana</div>
                      )}
                    </td>
                    <td className="py-2.5 text-center">
                      <button 
                        className="inline-flex items-center justify-center w-7 h-7 rounded bg-red-primary/10 hover:bg-red-primary/20 text-red-primary transition"
                        title="Zamknij pozycję"
                      >
                        <X size={14} />
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Podsumowanie */}
      {displayPositions.length > 0 && (
        <div className="mt-4 pt-3 border-t border-rldc-dark-border flex justify-between items-center text-xs">
          <div className="text-slate-400">
            Pozycji: <span className="text-slate-200 font-medium">{displayPositions.length}</span>
          </div>
          <div className="text-slate-400">
            Łączny P&L: <span className={`font-bold ${
              displayPositions.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0) >= 0
                ? 'text-green-primary'
                : 'text-red-primary'
            }`}>
              {displayPositions.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0) >= 0 ? '+' : ''}
              {displayPositions.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0).toFixed(4)} EUR
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
