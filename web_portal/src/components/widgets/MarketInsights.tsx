'use client'

import { getApiBase } from '@/lib/api'
import { AlertCircle, CheckCircle, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'

type Insight = {
  id: number
  symbol: string
  signal_type: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  reason: string
  timestamp: string
}

export default function MarketInsights() {
  const [insights, setInsights] = useState<Insight[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchSignals = async () => {
      try {
        const base = getApiBase()
        const res = await fetch(`${base}/api/signals/latest?limit=5`)
        if (!res.ok) {
          throw new Error('Błąd pobierania sygnałów')
        }
        const json = await res.json()
        if (!cancelled) setInsights(json.data || [])
      } catch (err) {
        if (!cancelled) setError('Nie udało się pobrać sygnałów')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchSignals()
    const interval = setInterval(fetchSignals, 60000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <div className="terminal-card rounded-lg p-5 border border-rldc-dark-border h-full neon-card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-200">AI Insights</h2>
        <button className="text-xs text-rldc-teal-primary hover:text-rldc-teal-light transition">
          Zobacz wszystkie
        </button>
      </div>

      {loading && <div className="text-sm text-slate-400">Ładowanie insights...</div>}
      {error && <div className="text-sm text-rldc-red-primary">{error}</div>}

      <div className="space-y-3">
        {insights.map((insight) => (
          <div
            key={insight.id}
            className="bg-rldc-dark-bg rounded-lg p-4 border border-rldc-dark-border hover:border-rldc-teal-primary/50 transition"
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center space-x-2">
                {insight.signal_type === 'BUY' && (
                  <TrendingUp size={16} className="text-rldc-green-primary" />
                )}
                {insight.signal_type === 'SELL' && (
                  <AlertCircle size={16} className="text-yellow-500" />
                )}
                {insight.signal_type === 'HOLD' && (
                  <CheckCircle size={16} className="text-rldc-teal-primary" />
                )}
                <h3 className="text-sm font-semibold text-slate-200">
                  {insight.symbol} {insight.signal_type}
                </h3>
              </div>
              <span className="text-xs text-slate-500">
                {new Date(insight.timestamp).toLocaleTimeString('pl-PL')}
              </span>
            </div>

            <p className="text-xs text-slate-400 mb-3 leading-relaxed">{insight.reason}</p>

            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <div className="text-xs text-slate-500">Pewność:</div>
                <div className="flex-1 bg-rldc-dark-border rounded-full h-1.5 w-20">
                  <div
                    className="bg-rldc-teal-primary h-1.5 rounded-full"
                    style={{ width: `${Math.round(insight.confidence * 100)}%` }}
                  />
                </div>
                <span className="text-xs font-medium text-rldc-teal-primary">
                  {Math.round(insight.confidence * 100)}%
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Quick Stats */}
      <div className="mt-6 pt-4 border-t border-rldc-dark-border">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Szybkie statystyki</h3>
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Aktywne sygnały</span>
            <span className="font-medium text-rldc-green-primary">{insights.length}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Średnia pewność</span>
            <span className="font-medium text-slate-200">78%</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Trafność 24h</span>
            <span className="font-medium text-rldc-green-primary">85%</span>
          </div>
        </div>
      </div>
    </div>
  )
}
