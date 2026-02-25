'use client'

import React, { useEffect, useState } from 'react'
import { API_BASE, withAdminToken } from '../../lib/api'

type PositionItem = {
  id: number
  symbol: string
  side: 'LONG' | 'SHORT'
  quantity: number
  entry_price: number
  current_price: number
  unrealized_pnl: number
  pnl_percent: number
}

export default function OpenOrders() {
  const [positions, setPositions] = useState<PositionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionStatus, setActionStatus] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchPositions = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/positions?mode=demo`)
        if (!res.ok) {
          throw new Error('Błąd pobierania pozycji')
        }
        const json = await res.json()
        if (!cancelled) setPositions(json.data || [])
      } catch (err) {
        if (!cancelled) setError('Nie udało się pobrać pozycji')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchPositions()
    const interval = setInterval(fetchPositions, 60000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const refresh = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/positions?mode=demo`)
      if (!res.ok) throw new Error('Błąd odświeżania pozycji')
      const json = await res.json()
      setPositions(json.data || [])
    } catch (e) {
      // ignore
    }
  }

  const closeOne = async (positionId: number) => {
    setActionStatus(`Zamykam #${positionId}...`)
    try {
      const res = await fetch(`${API_BASE}/api/positions/${positionId}/close?mode=demo`, {
        method: 'POST',
        headers: withAdminToken(),
      })
      if (!res.ok) {
        const msg = res.status === 401 ? '401 Unauthorized (ADMIN_TOKEN?)' : 'Błąd zamknięcia'
        throw new Error(msg)
      }
      setActionStatus('OK (utworzono pending)')
      await refresh()
    } catch (e: any) {
      setActionStatus(String(e?.message || 'Błąd zamknięcia'))
    }
  }

  const closeAll = async () => {
    setActionStatus('Zamykam wszystkie...')
    try {
      const res = await fetch(`${API_BASE}/api/positions/close-all?mode=demo`, {
        method: 'POST',
        headers: withAdminToken(),
      })
      if (!res.ok) {
        const msg = res.status === 401 ? '401 Unauthorized (ADMIN_TOKEN?)' : 'Błąd zamknięcia'
        throw new Error(msg)
      }
      setActionStatus('OK (utworzono pendingy)')
      await refresh()
    } catch (e: any) {
      setActionStatus(String(e?.message || 'Błąd zamknięcia'))
    }
  }

  const totalPnl = positions.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0)

  return (
    <div className="terminal-card rounded-lg p-5 border border-rldc-dark-border neon-card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-200">Otwarte Pozycje</h2>
        <div className="flex space-x-2">
          <button className="px-3 py-1 text-xs rounded bg-rldc-dark-bg text-slate-400 hover:bg-rldc-teal-primary hover:text-white transition">
            Wszystkie
          </button>
          <button className="px-3 py-1 text-xs rounded bg-rldc-dark-bg text-slate-400 hover:bg-rldc-teal-primary hover:text-white transition">
            Aktywne
          </button>
          <button className="px-3 py-1 text-xs rounded bg-rldc-dark-bg text-slate-400 hover:bg-rldc-teal-primary hover:text-white transition">
            Zamknięte
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        {loading && <div className="text-sm text-slate-400">Ładowanie pozycji...</div>}
        {error && <div className="text-sm text-rldc-red-primary">{error}</div>}
        {actionStatus && <div className="text-xs text-slate-400 mb-2">{actionStatus}</div>}
        <table className="w-full font-mono text-[12px]">
          <thead>
            <tr className="border-b border-rldc-dark-border text-left text-[10px] uppercase tracking-widest text-slate-500">
              <th className="pb-3 font-medium">Para</th>
              <th className="pb-3 font-medium">Typ</th>
              <th className="pb-3 font-medium">Rozmiar</th>
              <th className="pb-3 font-medium">Wejście</th>
              <th className="pb-3 font-medium">Obecna</th>
              <th className="pb-3 font-medium">P&L</th>
              <th className="pb-3 font-medium">Status</th>
              <th className="pb-3 font-medium">Akcje</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((order) => (
              <tr
                key={order.id}
                className="border-b border-rldc-dark-border/50 hover:bg-rldc-dark-hover transition"
              >
                <td className="py-3 text-sm font-medium text-slate-200">{order.symbol}</td>
                <td className="py-3">
                  <span
                    className={`px-2 py-1 rounded text-xs font-medium ${
                      order.side === 'LONG'
                        ? 'bg-rldc-green-primary/20 text-rldc-green-primary'
                        : 'bg-rldc-red-primary/20 text-rldc-red-primary'
                    }`}
                  >
                    {order.side}
                  </span>
                </td>
                <td className="py-3 text-sm text-slate-300">{order.quantity}</td>
                <td className="py-3 text-sm text-slate-300">${order.entry_price.toFixed(2)}</td>
                <td className="py-3 text-sm text-slate-300">${order.current_price?.toFixed(2)}</td>
                <td className="py-3">
                  <div className="text-sm font-medium text-rldc-green-primary">
                    {order.unrealized_pnl >= 0 ? '+' : ''}${order.unrealized_pnl.toFixed(2)}
                  </div>
                  <div className="text-xs text-rldc-green-primary/70">
                    {order.unrealized_pnl >= 0 ? '+' : ''}{order.pnl_percent.toFixed(2)}%
                  </div>
                </td>
                <td className="py-3">
                  <span className="px-2 py-1 rounded text-xs font-medium bg-rldc-teal-primary/20 text-rldc-teal-primary">
                    aktywna
                  </span>
                </td>
                <td className="py-3">
                  <button
                    onClick={() => closeOne(order.id)}
                    className="px-3 py-1 text-xs rounded bg-rldc-red-primary/20 text-rldc-red-primary hover:bg-rldc-red-primary hover:text-white transition"
                  >
                    Zamknij
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Summary */}
      <div className="mt-4 pt-4 border-t border-rldc-dark-border flex items-center justify-between">
        <div className="flex space-x-6">
          <div>
            <div className="text-xs text-slate-500 mb-1">Całkowity P&L</div>
            <div className="text-lg font-bold text-rldc-green-primary">
              {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">ROI</div>
            <div className="text-lg font-bold text-rldc-green-primary">--</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Otwarte pozycje</div>
            <div className="text-lg font-bold text-slate-200">{positions.length}</div>
          </div>
        </div>
        
        <button
          onClick={() => closeAll()}
          className="px-4 py-2 bg-rldc-red-primary hover:bg-red-600 text-white rounded-lg text-sm font-medium transition"
        >
          Zamknij wszystkie
        </button>
      </div>
    </div>
  )
}
