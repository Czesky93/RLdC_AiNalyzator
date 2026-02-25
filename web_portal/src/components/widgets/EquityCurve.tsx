'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { API_BASE } from '../../lib/api'

type Point = {
  t: string
  equity: number
  free_margin: number
  unrealized_pnl: number
}

export default function EquityCurve({
  mode,
  hours = 24,
  quoteCcy,
  refreshMs = 60000,
  title = 'Equity Curve',
}: {
  mode: 'demo' | 'live'
  hours?: number
  quoteCcy?: string
  refreshMs?: number
  title?: string
}) {
  const [data, setData] = useState<Point[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`${API_BASE}/api/account/history?mode=${mode}&hours=${hours}`)
        if (!res.ok) throw new Error('Błąd pobierania historii')
        const json = await res.json()
        const items = (json.data || []) as any[]
        const mapped = items.map((p) => ({
          t: new Date(p.timestamp).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }),
          equity: Number(p.equity) || 0,
          free_margin: Number(p.free_margin) || 0,
          unrealized_pnl: Number(p.unrealized_pnl) || 0,
        }))
        if (!cancelled) setData(mapped)
      } catch {
        if (!cancelled) setError('Nie udało się pobrać historii equity')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const interval = setInterval(load, refreshMs)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [mode, hours, refreshMs])

  const ccy = (quoteCcy || '').trim().toUpperCase()

  const domain = useMemo(() => {
    if (!data.length) return undefined
    const vals = data.map((d) => d.equity)
    const min = Math.min(...vals)
    const max = Math.max(...vals)
    const pad = (max - min) * 0.05 || max * 0.01 || 1
    return [min - pad, max + pad]
  }, [data])

  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card terminal-card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">{title}</h2>
          <div className="text-xs text-slate-500 mt-1">
            {mode.toUpperCase()} • last {hours}h • {ccy || '--'}
          </div>
        </div>
      </div>

      <div className="h-56 rldc-chart bg-[#0b121a] border border-rldc-dark-border/60">
        {loading && <div className="text-sm text-slate-400">Ładowanie...</div>}
        {error && <div className="text-sm text-rldc-red-primary">{error}</div>}
        {!loading && !error && (
          <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
            <AreaChart data={data}>
              <defs>
                <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2a37" />
              <XAxis dataKey="t" tick={{ fill: '#94a3b8', fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                width={50}
                domain={domain as any}
                tickFormatter={(v) => String(Math.round(Number(v)))}
              />
              <Tooltip
                contentStyle={{
                  background: '#0b121a',
                  border: '1px solid rgba(148, 163, 184, 0.2)',
                  borderRadius: 8,
                  color: '#e2e8f0',
                  fontSize: 12,
                }}
                formatter={(value: any, name: any) => [value, name]}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Area type="monotone" dataKey="equity" stroke="#0ea5e9" fillOpacity={1} fill="url(#colorEquity)" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

