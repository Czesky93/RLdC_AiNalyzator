'use client'

import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { API_BASE } from '../../lib/api'

interface Position {
  symbol: string
  side: 'LONG' | 'SHORT'
  quantity: number
  entry_price: number
  current_price: number
  pnl: number
  pnl_percent: number
}

export default function PositionsTable() {
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchPositions = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/positions`)
        if (res.ok) {
          const data = await res.json()
          setPositions(data.positions || [])
        }
      } catch (error) {
        console.error('Błąd pobierania pozycji:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchPositions()
    const interval = setInterval(fetchPositions, 5000)
    return () => clearInterval(interval)
  }, [])

  // Mock data jeśli brak danych z API
  const displayPositions = positions.length > 0 ? positions : [
    {
      symbol: 'BTCLUSDT',
      side: 'LONG' as const,
      quantity: 0.500,
      entry_price: 63287.89,
      current_price: 63360.00,
      pnl: 36.06,
      pnl_percent: 0.11
    },
    {
      symbol: 'ETHUSDT',
      side: 'SHORT' as const,
      quantity: 5.0,
      entry_price: 3128.90,
      current_price: 3112.45,
      pnl: 82.25,
      pnl_percent: 0.53
    }
  ]

  return (
    <div className="terminal-card rounded-lg p-4 border border-rldc-dark-border">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200">Open Orders & Positions</h2>
        <div className="flex items-center space-x-2">
          <span className="text-[10px] uppercase tracking-widest text-teal-primary font-medium">
            {displayPositions.length} positions
          </span>
          <div className="text-[10px] uppercase tracking-widest text-slate-500">LIVE</div>
        </div>
      </div>
      
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-[11px]">
          <thead>
            <tr className="border-b border-rldc-dark-border text-left text-[10px] uppercase tracking-widest text-slate-500">
              <th className="pb-3 font-medium">Number</th>
              <th className="pb-3 font-medium">Symbol</th>
              <th className="pb-3 font-medium">Side</th>
              <th className="pb-3 font-medium text-right">Qty</th>
              <th className="pb-3 font-medium text-right">Entry</th>
              <th className="pb-3 font-medium text-right">Current</th>
              <th className="pb-3 font-medium text-right">P&L</th>
              <th className="pb-3 font-medium text-center">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-slate-400">
                  Ładowanie pozycji...
                </td>
              </tr>
            ) : displayPositions.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-slate-400">
                  Brak otwartych pozycji
                </td>
              </tr>
            ) : (
              displayPositions.map((position, idx) => {
                const isPnlPositive = position.pnl >= 0
                return (
                  <tr key={idx} className="table-row">
                    <td className="py-2.5 text-slate-400">{idx + 1}</td>
                    <td className="py-2.5 text-slate-300 font-medium">{position.symbol}</td>
                    <td className="py-2.5">
                      <span className={`badge-${position.side === 'LONG' ? 'success' : 'danger'}`}>
                        {position.side}
                      </span>
                    </td>
                    <td className="py-2.5 text-right text-slate-300">{position.quantity}</td>
                    <td className="py-2.5 text-right text-slate-400">${position.entry_price.toFixed(2)}</td>
                    <td className="py-2.5 text-right text-slate-300">${position.current_price.toFixed(2)}</td>
                    <td className={`py-2.5 text-right font-semibold ${isPnlPositive ? 'text-green-primary' : 'text-red-primary'}`}>
                      {isPnlPositive ? '+' : ''}${position.pnl.toFixed(2)}
                      <span className="text-xs ml-1">({isPnlPositive ? '+' : ''}{position.pnl_percent.toFixed(2)}%)</span>
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

      {/* Summary Footer */}
      {displayPositions.length > 0 && (
        <div className="mt-4 pt-3 border-t border-rldc-dark-border flex justify-between items-center text-xs">
          <div className="text-slate-400">
            Total Positions: <span className="text-slate-200 font-medium">{displayPositions.length}</span>
          </div>
          <div className="text-slate-400">
            Total P&L: <span className={`font-bold ${
              displayPositions.reduce((sum, p) => sum + p.pnl, 0) >= 0 
                ? 'text-green-primary' 
                : 'text-red-primary'
            }`}>
              {displayPositions.reduce((sum, p) => sum + p.pnl, 0) >= 0 ? '+' : ''}
              ${displayPositions.reduce((sum, p) => sum + p.pnl, 0).toFixed(2)}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
