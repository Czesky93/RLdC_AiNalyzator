'use client'

import React, { useEffect, useState } from 'react'

type AccountSummary = {
  equity: number
  free_margin: number
  used_margin: number
  margin_level: number
  balance: number
  unrealized_pnl: number
  timestamp: string
}

export default function AccountSummary() {
  const [data, setData] = useState<AccountSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchSummary = async () => {
      try {
        const base = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
        const res = await fetch(`${base}/api/account/summary?mode=demo`)
        if (!res.ok) {
          throw new Error('Błąd pobierania account summary')
        }
        const json = await res.json()
        setData(json.data)
      } catch (err) {
        setError('Nie udało się pobrać danych konta')
      } finally {
        setLoading(false)
      }
    }
    fetchSummary()
  }, [])

  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-200">Podsumowanie Konta</h2>
        <span className="text-xs text-slate-500">
          {data?.timestamp ? new Date(data.timestamp).toLocaleTimeString('pl-PL') : '--'}
        </span>
      </div>

      {loading && <div className="text-sm text-slate-400">Ładowanie danych...</div>}
      {error && <div className="text-sm text-rldc-red-primary">{error}</div>}

      {data && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-slate-500 mb-1">Equity</div>
            <div className="text-lg font-bold text-slate-100">${data.equity.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Balance</div>
            <div className="text-lg font-bold text-slate-100">${data.balance.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Free Margin</div>
            <div className="text-lg font-bold text-rldc-green-primary">${data.free_margin.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Used Margin</div>
            <div className="text-lg font-bold text-slate-100">${data.used_margin.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Margin Level</div>
            <div className="text-lg font-bold text-slate-100">{data.margin_level.toFixed(2)}%</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Unrealized PnL</div>
            <div className="text-lg font-bold text-rldc-green-primary">${data.unrealized_pnl.toFixed(2)}</div>
          </div>
        </div>
      )}
    </div>
  )
}
