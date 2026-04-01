'use client'

import { getApiBase } from '@/lib/api'
import { useEffect, useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type KlinePoint = {
  time: string
  price: number
  volume: number
  ema20?: number
  ema50?: number
}

type RsiPoint = {
  time: string
  rsi: number | undefined
}

function calcEma(closes: number[], period: number): (number | undefined)[] {
  const k = 2 / (period + 1)
  const result: (number | undefined)[] = Array(closes.length).fill(undefined)
  let ema: number | undefined
  for (let i = 0; i < closes.length; i++) {
    if (ema === undefined) {
      if (i >= period - 1) ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period
    } else {
      ema = closes[i] * k + ema * (1 - k)
    }
    result[i] = ema
  }
  return result
}

function calcRsi(closes: number[], period = 14): (number | undefined)[] {
  const result: (number | undefined)[] = Array(closes.length).fill(undefined)
  for (let i = period; i < closes.length; i++) {
    let gains = 0, losses = 0
    for (let j = i - period + 1; j <= i; j++) {
      const diff = closes[j] - closes[j - 1]
      if (diff > 0) gains += diff; else losses += -diff
    }
    const rs = losses === 0 ? 100 : gains / losses
    result[i] = 100 - 100 / (1 + rs)
  }
  return result
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
  const [rsiData, setRsiData] = useState<RsiPoint[]>([])
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
    // Reset danych natychmiast przy zmianie symbolu/timeframe — zapobiega "ciągłej linii"
    setData([])
    setRsiData([])
    setLastPrice(null)
    setRange(null)
    setDecision(null)

    const normalized = normalizeSymbol(fixedSymbol || symbol)
    let cancelled = false

    const fetchKlines = async () => {
      setLoading(true)
      setError(null)
      try {
        const base = getApiBase()
        const res = await fetch(`${base}/api/market/kline?symbol=${normalized}&tf=${timeframe}&limit=120`)
        if (cancelled) return
        if (!res.ok) {
          throw new Error('Błąd pobierania świec')
        }
        const json = await res.json()
        const sorted = (json.data || []).sort(
          (a: any, b: any) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
        )
        const closes = sorted.map((k: any) => k.close as number)
        const ema20vals = calcEma(closes, 20)
        const ema50vals = calcEma(closes, 50)
        const rsiVals = calcRsi(closes, 14)
        const mapped = sorted.map((k: any, i: number) => ({
          time: new Date(k.timestamp).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }),
          price: k.close,
          volume: k.volume,
          ema20: ema20vals[i],
          ema50: ema50vals[i],
        }))
        const rsiPoints = sorted.map((k: any, i: number) => ({
          time: new Date(k.timestamp).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }),
          rsi: rsiVals[i] !== undefined ? Math.round(rsiVals[i]! * 10) / 10 : undefined,
        }))
        if (!cancelled) {
          setData(mapped)
          setRsiData(rsiPoints)
          if (mapped.length > 0) {
            setLastPrice(mapped[mapped.length - 1].price)
          }
          setLastUpdate(new Date().toLocaleTimeString('pl-PL'))
        }
      } catch (err) {
        if (!cancelled) setError('Nie udało się pobrać danych wykresu')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchKlines()
    const interval = setInterval(fetchKlines, refreshMs)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [timeframe, symbol, fixedSymbol, refreshMs])

  useEffect(() => {
    const normalized = normalizeSymbol(fixedSymbol || symbol)
    let cancelled = false

    const fetchRange = async () => {
      try {
        const base = getApiBase()
        const res = await fetch(`${base}/api/market/ranges?symbol=${normalized}`)
        if (cancelled || !res.ok) return
        const json = await res.json()
        const r = json.data?.[0] || null
        if (!cancelled) {
          setRange(r)
          if (r) {
            const buy = r.buy_action ? `${r.buy_action} (cel: ${r.buy_target})` : 'CZEKAJ'
            const sell = r.sell_action ? `${r.sell_action} (cel: ${r.sell_target})` : 'CZEKAJ'
            setDecision({ buy, sell })
          } else {
            setDecision(null)
          }
        }
      } catch (err) {
        if (!cancelled) {
          setRange(null)
          setDecision(null)
        }
      }
    }
    fetchRange()
    const interval = setInterval(fetchRange, refreshMs)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [symbol, fixedSymbol, refreshMs])

  useEffect(() => {
    const fetchSymbols = async () => {
      try {
        const base = getApiBase()
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

  const lastRsi = rsiData.length > 0
    ? [...rsiData].reverse().find(p => p.rsi !== undefined)?.rsi ?? null
    : null

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
              title="Wybór symbolu"
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

      <div className="rldc-chart bg-[#0b121a] border border-rldc-dark-border/60">
        <div className="h-72">
          {loading && <div className="text-sm text-slate-400 px-4 py-2">Ładowanie wykresu...</div>}
          {error && <div className="text-sm text-rldc-red-primary px-4 py-2">{error}</div>}
          {mounted && (
            <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
              <ComposedChart data={data}>
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
                  formatter={(val: any, name: string | undefined) => [
                    val != null ? String(val) : '--',
                    name === 'price' ? 'Cena' : name === 'ema20' ? 'EMA 20' : name === 'ema50' ? 'EMA 50' : (name ?? '')
                  ]}
                />
                <Area
                  type="monotone"
                  dataKey="price"
                  stroke="#16f2a3"
                  strokeWidth={2}
                  fill="url(#colorPrice)"
                  name="price"
                />
                <Line type="monotone" dataKey="ema20" stroke="#fbbf24" dot={false} strokeWidth={1} connectNulls name="ema20" />
                <Line type="monotone" dataKey="ema50" stroke="#7c3aed" dot={false} strokeWidth={1} connectNulls name="ema50" />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Mini RSI panel */}
        <div className="h-16 border-t border-rldc-dark-border/40">
          <div className="flex items-center justify-between px-2 pt-1">
            <span className="text-[9px] text-slate-500 uppercase tracking-widest">RSI (14)</span>
            {lastRsi != null && (
              <span className={`text-[10px] font-mono font-bold ${
                lastRsi < 30 ? 'text-rldc-green-primary' : lastRsi > 70 ? 'text-rldc-red-primary' : 'text-slate-300'
              }`}>
                {Math.round(lastRsi)}
                {lastRsi < 30 ? ' (wyprzedanie)' : lastRsi > 70 ? ' (wykupienie)' : ''}
              </span>
            )}
          </div>
          {mounted && rsiData.length > 0 && (
            <ResponsiveContainer width="100%" height={40} minWidth={0} minHeight={0}>
              <LineChart data={rsiData} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="time" hide />
                <YAxis domain={[0, 100]} tick={{ fontSize: 8, fill: '#64748b' }} width={30} tickCount={3} ticks={[30, 50, 70]} />
                <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="2 2" strokeWidth={0.8} />
                <ReferenceLine y={30} stroke="#22c55e" strokeDasharray="2 2" strokeWidth={0.8} />
                <Line type="monotone" dataKey="rsi" stroke="#a78bfa" dot={false} strokeWidth={1.2} connectNulls name="rsi" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Legenda wskaźników */}
      <div className="flex items-center gap-3 mt-2 flex-wrap">
        <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="inline-block w-3 h-0.5 bg-rldc-teal-primary"></span> Cena</span>
        <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="inline-block w-3 h-0.5 bg-yellow-400"></span> EMA 20</span>
        <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="inline-block w-3 h-0.5 bg-purple-600"></span> EMA 50</span>
        <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="inline-block w-3 h-0.5 bg-purple-300"></span> RSI(14)</span>
      </div>

    </div>
  )
}
