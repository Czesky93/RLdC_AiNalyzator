'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart, ReferenceArea, ReferenceLine } from 'recharts'

type KlinePoint = {
  time: string
  price: number
  volume: number
}

interface TradingViewProps {
  symbol?: string
  allowSymbolSelect?: boolean
  titleOverride?: string
  refreshMs?: number
  onSymbolChange?: (symbol: string) => void
}

export default function TradingView({
  symbol: symbolProp,
  allowSymbolSelect = true,
  titleOverride: titleOverrideProp,
  refreshMs: refreshMsProp = 60000,
  onSymbolChange,
}: TradingViewProps) {
  const [mounted, setMounted] = useState(false)
  const [timeframe, setTimeframe] = useState('1h')
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [data, setData] = useState<KlinePoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastPrice, setLastPrice] = useState<number | null>(null)
  const [lastUpdate, setLastUpdate] = useState<string | null>(null)
  const [range, setRange] = useState<any | null>(null)
  const [symbols, setSymbols] = useState<string[]>([])
  const [decision, setDecision] = useState<{ buy: string, sell: string } | null>(null)
  const [fixedSymbol, setFixedSymbol] = useState<string | null>(null)
  const [allowSelect, setAllowSelect] = useState<boolean>(true)
  const [titleOverride, setTitleOverride] = useState<string | null>(null)
  const [refreshMs, setRefreshMs] = useState<number>(60000)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    setFixedSymbol(symbolProp || null)
    setAllowSelect(allowSymbolSelect)
    setTitleOverride(titleOverrideProp || null)
    setRefreshMs(refreshMsProp)
    if (symbolProp) {
      setSymbol(symbolProp)
    }
  }, [symbolProp, allowSymbolSelect, titleOverrideProp, refreshMsProp])

  useEffect(() => {
    const fetchKlines = async (s: string) => {
      setLoading(true)
      setError(null)
      try {
        const base = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
        const res = await fetch(`${base}/api/market/kline?symbol=${s}&tf=${timeframe}&limit=120`)
        if (!res.ok) {
          throw new Error('Błąd pobierania świec')
        }
        const json = await res.json()
        const mapped = (json.data || []).map((k: any) => ({
          time: new Date(k.timestamp).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }),
          price: k.close,
          volume: k.volume,
        }))
        setData(mapped)
        if (mapped.length > 0) {
          setLastPrice(mapped[mapped.length - 1].price)
        }
        setLastUpdate(new Date().toLocaleTimeString('pl-PL'))
      } catch (err) {
        setError('Nie udało się pobrać danych wykresu')
      } finally {
        setLoading(false)
      }
    }
    const normalized = normalizeSymbol(fixedSymbol || symbol)
    fetchKlines(normalized)
    const interval = setInterval(() => fetchKlines(normalized), refreshMs)
    return () => clearInterval(interval)
  }, [timeframe, symbol, fixedSymbol, refreshMs])

  useEffect(() => {
    const fetchRange = async (s: string) => {
      try {
        const base = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
        const res = await fetch(`${base}/api/market/ranges?symbol=${s}`)
        if (!res.ok) return
        const json = await res.json()
        const r = json.data?.[0] || null
        setRange(r)
        if (r) {
          const buy = r.buy_action ? `${r.buy_action} (cel: ${r.buy_target})` : 'CZEKAJ'
          const sell = r.sell_action ? `${r.sell_action} (cel: ${r.sell_target})` : 'CZEKAJ'
          setDecision({ buy, sell })
        } else {
          setDecision(null)
        }
      } catch (err) {
        setRange(null)
        setDecision(null)
      }
    }
    const normalized = normalizeSymbol(fixedSymbol || symbol)
    fetchRange(normalized)
    const interval = setInterval(() => fetchRange(normalized), refreshMs)
    return () => clearInterval(interval)
  }, [symbol, fixedSymbol, refreshMs])

  useEffect(() => {
    const fetchSymbols = async () => {
      try {
        const base = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
        const res = await fetch(`${base}/api/market/summary`)
        if (!res.ok) return
        const json = await res.json()
        const list = (json.data || []).map((m: any) => m.symbol)
        setSymbols(list)
        if (!fixedSymbol && list.length > 0 && !list.includes(symbol)) {
          setSymbol(list[0])
        }
      } catch (err) {
        // ignore
      }
    }
    fetchSymbols()
  }, [symbol, fixedSymbol])

  function normalizeSymbol(s: string) {
    return s.includes('/') ? s.replace('/', '') : s
  }

  function toNum(value: any): number | null {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }

  const displayTitle = useMemo(() => {
    if (titleOverride) return titleOverride
    return `Wykres ${fixedSymbol || symbol}`
  }, [fixedSymbol, symbol, titleOverride])

  function formatPrice(v: number | null) {
    if (v === null) return '--'
    if (v < 1) return v.toFixed(4)
    if (v < 1000) return v.toFixed(2)
    return v.toFixed(2)
  }

  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card terminal-card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">{displayTitle}</h2>
          <div className="flex items-center space-x-4 mt-1">
            <span className="text-2xl font-bold text-rldc-green-primary">
              {formatPrice(lastPrice)}
            </span>
            <span className="text-sm text-slate-400">
              Ostatnia aktualizacja: {lastUpdate || '--'}
            </span>
          </div>
          {range && (
            <div className="text-sm text-slate-200 mt-2">
              Co robić teraz: <span className="font-semibold">{decision?.buy?.includes('KUP') ? 'KUP' : decision?.sell?.includes('SPRZEDAJ') ? 'SPRZEDAJ' : 'CZEKAJ'}</span>
            </div>
          )}
        </div>
        
        <div className="flex space-x-2 items-center">
          {allowSelect && (
            <select
              value={symbol}
              onChange={(e) => {
                const next = e.target.value
                setSymbol(next)
                if (onSymbolChange) {
                  onSymbolChange(normalizeSymbol(next))
                }
              }}
              className="bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 text-xs rounded px-2 py-1"
            >
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          )}
          {['1m', '5m', '15m', '1h', '4h', '1d'].map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1 text-xs rounded transition ${
                timeframe === tf
                  ? 'bg-rldc-teal-primary text-white'
                  : 'bg-rldc-dark-bg text-slate-400 hover:bg-rldc-teal-primary hover:text-white'
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="h-96 rldc-chart bg-[#0b121a] border border-rldc-dark-border/60">
        {loading && <div className="text-sm text-slate-400">Ładowanie wykresu...</div>}
        {error && <div className="text-sm text-rldc-red-primary">{error}</div>}
        {mounted && (
          <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
            <AreaChart data={data}>
              <defs>
                <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#16f2a3" stopOpacity={0.35}/>
                  <stop offset="95%" stopColor="#16f2a3" stopOpacity={0}/>
                </linearGradient>
              </defs>
              {range && (
                <>
                  {toNum(range.buy_target) !== null && (
                    <ReferenceLine
                      y={toNum(range.buy_target) as number}
                      stroke="#16f2a3"
                      strokeDasharray="6 6"
                      label={{ value: `BUY target ${range.buy_target}`, position: 'insideTopRight', fill: '#7cfde0', fontSize: 11 }}
                    />
                  )}
                  {toNum(range.sell_target) !== null && (
                    <ReferenceLine
                      y={toNum(range.sell_target) as number}
                      stroke="#ef4444"
                      strokeDasharray="6 6"
                      label={{ value: `SELL target ${range.sell_target}`, position: 'insideTopLeft', fill: '#fca5a5', fontSize: 11 }}
                    />
                  )}
                  <ReferenceArea
                    y1={range.buy_low}
                    y2={range.buy_high}
                    strokeOpacity={0}
                    fill="#16f2a3"
                    fillOpacity={0.18}
                  />
                  <ReferenceArea
                    y1={range.sell_low}
                    y2={range.sell_high}
                    strokeOpacity={0}
                    fill="#ef4444"
                    fillOpacity={0.16}
                  />
                </>
              )}
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2d3d" />
              <XAxis 
                dataKey="time" 
                stroke="#64748b"
                style={{ fontSize: '12px' }}
              />
              <YAxis 
                stroke="#64748b"
                style={{ fontSize: '12px' }}
                domain={['dataMin - 10', 'dataMax + 10']}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#111c26',
                  border: '1px solid #1e2d3d',
                  borderRadius: '8px',
                  color: '#f1f5f9'
                }}
              />
              <Area 
                type="monotone" 
                dataKey="price" 
                stroke="#16f2a3" 
                strokeWidth={2}
                fill="url(#colorPrice)" 
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

    </div>
  )
}
