'use client'

import { getApiBase } from '@/lib/api'
import { useEffect, useState } from 'react'

type Orderbook = {
  bids: [number, number][]
  asks: [number, number][]
}

export default function Orderbook() {
  const [data, setData] = useState<Orderbook | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchOrderbook = async () => {
      try {
        const base = getApiBase()
        const res = await fetch(`${base}/api/market/orderbook/BTCEUR?limit=10`)
        if (!res.ok) {
          throw new Error('Błąd pobierania orderbook')
        }
        const json = await res.json()
        setData({ bids: json.bids || [], asks: json.asks || [] })
      } catch (err) {
        setError('Nie udało się pobrać orderbook')
      } finally {
        setLoading(false)
      }
    }
    fetchOrderbook()
  }, [])

  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
      <h2 className="text-lg font-semibold text-slate-200 mb-4">Orderbook BTC/EUR</h2>

      {loading && <div className="text-sm text-slate-400">Ładowanie orderbook...</div>}
      {error && <div className="text-sm text-rldc-red-primary">{error}</div>}

      {data && (
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-xs text-slate-500 mb-2">BID</div>
            {data.bids.map((b, idx) => (
              <div key={`b-${idx}`} className="flex items-center justify-between text-rldc-green-primary">
                <span>${b[0].toFixed(2)}</span>
                <span>{b[1].toFixed(4)}</span>
              </div>
            ))}
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-2">ASK</div>
            {data.asks.map((a, idx) => (
              <div key={`a-${idx}`} className="flex items-center justify-between text-rldc-red-primary">
                <span>${a[0].toFixed(2)}</span>
                <span>{a[1].toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
