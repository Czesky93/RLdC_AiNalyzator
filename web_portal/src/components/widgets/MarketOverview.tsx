'use client'

import { getApiBase } from '@/lib/api'
import { TrendingDown, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'

type MarketItem = {
  symbol: string
  price: number
  price_change: number
  price_change_percent: number
  volume?: number
  last_update?: string
}

export default function MarketOverview() {
  const [data, setData] = useState<MarketItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const base = getApiBase()
        const res = await fetch(`${base}/api/market/summary`)
        if (!res.ok) {
          throw new Error('Błąd pobierania danych rynku')
        }
        const json = await res.json()
        setData(json.data || [])
      } catch (err) {
        setError('Nie udało się pobrać danych rynku')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
      <h2 className="text-lg font-semibold mb-4 text-slate-200">Przegląd Rynku</h2>

      {loading && (
        <div className="text-sm text-slate-400">Ładowanie danych...</div>
      )}
      {error && (
        <div className="text-sm text-rldc-red-primary">{error}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {data.map((item) => (
          <div
            key={item.symbol}
            className="bg-rldc-dark-bg rounded-lg p-4 border border-rldc-dark-border hover:border-rldc-teal-primary/50 transition neon-card"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-slate-400">{item.symbol}</span>
              {item.price_change >= 0 ? (
                <TrendingUp size={16} className="text-rldc-green-primary" />
              ) : (
                <TrendingDown size={16} className="text-rldc-red-primary" />
              )}
            </div>
            
            <div className="text-2xl font-bold text-slate-100 mb-1">
              ${item.price?.toFixed(2)}
            </div>
            
            <div className="flex items-center justify-between text-sm">
              <span className={item.price_change >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}>
                {item.price_change >= 0 ? '+' : ''}{item.price_change.toFixed(2)} ({item.price_change_percent.toFixed(2)}%)
              </span>
              <span className="text-slate-500">{item.volume?.toFixed(2)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
