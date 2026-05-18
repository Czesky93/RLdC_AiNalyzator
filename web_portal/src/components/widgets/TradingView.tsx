'use client'

import { getApiBase } from '@/lib/api'
import { useEffect, useMemo, useState } from 'react'
import BinanceStyleChart from './BinanceStyleChart'

type KlinePoint = {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

type ForecastPoint = {
  timestamp: number
  value: number
}

type RangeData = {
  buy_low?: number | null
  buy_high?: number | null
  sell_low?: number | null
  sell_high?: number | null
  buy_target?: number | null
  sell_target?: number | null
  comment?: string | null
}

type OrderbookMeta = {
  bestBid?: number | null
  bestAsk?: number | null
  spreadBps?: number | null
  bidDepth?: number | null
  askDepth?: number | null
  imbalance?: number | null
}

type DecisionView = {
  final_signal?: string
  final_signal_reason?: string
  recommended_action_label?: string
  plain_explanation?: string
  data_quality?: string
  final_confidence?: number | null
  indicators?: Record<string, number | string | null | undefined>
  horizons?: Record<string, { direction?: string | null; projected_pct?: number | null; forecast_price?: number | null }>
  blockers?: string[]
}

interface TradingViewProps {
  symbol?: string
  allowSymbolSelect?: boolean
  titleOverride?: string
  refreshMs?: number
  onSymbolChange?: (symbol: string) => void
}

function normalizeSymbol(symbol: string) {
  return symbol.includes('/') ? symbol.replace('/', '') : symbol
}

function parseTimestamp(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1_000_000_000_000 ? value : value * 1000
  }
  if (typeof value === 'string') {
    const parsed = Date.parse(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return Date.now()
}

function toNum(value: unknown) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function timeframeMs(timeframe: string) {
  if (timeframe === '1m') return 60_000
  if (timeframe === '5m') return 5 * 60_000
  if (timeframe === '15m') return 15 * 60_000
  if (timeframe === '1h') return 60 * 60_000
  if (timeframe === '4h') return 4 * 60 * 60_000
  if (timeframe === '1d') return 24 * 60 * 60_000
  return 60_000
}

function formatPrice(value: number | null) {
  if (value === null) return '--'
  if (Math.abs(value) < 0.01) return value.toFixed(8)
  if (Math.abs(value) < 1) return value.toFixed(5)
  if (Math.abs(value) < 100) return value.toFixed(4)
  return value.toFixed(2)
}

function buildForecastPoints(payload: any, timeframe: string, lastTimestamp: number, lastClose: number | null): ForecastPoint[] {
  const direct = Array.isArray(payload?.data)
    ? payload.data
        .map((item: any) => ({
          timestamp: parseTimestamp(item?.timestamp ?? item?.forecast_ts ?? item?.time),
          value: toNum(item?.price ?? item?.forecast_price ?? item?.projected_price),
        }))
        .filter((item: { value: number | null }) => item.value !== null)
        .map((item: { timestamp: number; value: number | null }) => ({ timestamp: item.timestamp, value: item.value as number }))
    : []
  if (direct.length > 0) return direct.sort((a: ForecastPoint, b: ForecastPoint) => a.timestamp - b.timestamp)

  const basePrice = lastClose ?? toNum(payload?.current_price)
  if (basePrice === null) return []
  const step = timeframeMs(timeframe)
  const meta = [
    { key: 'forecast_1h', offset: 1 },
    { key: 'forecast_4h', offset: 4 },
    { key: 'forecast_24h', offset: 24 },
  ]
  const derived = meta
    .map(({ key, offset }) => ({
      timestamp: lastTimestamp + offset * step,
      value: toNum(payload?.[key]?.projected_price ?? payload?.[key]?.forecast_price),
    }))
    .filter((item: { value: number | null }) => item.value !== null)
    .map((item: { timestamp: number; value: number | null }) => ({ timestamp: item.timestamp, value: item.value as number }))

  return derived.length > 0 ? [{ timestamp: lastTimestamp, value: basePrice }, ...derived] : []
}

function buildOrderbookMeta(payload: any): OrderbookMeta | null {
  const bids = Array.isArray(payload?.bids) ? payload.bids : []
  const asks = Array.isArray(payload?.asks) ? payload.asks : []
  const bestBid = toNum(bids[0]?.[0])
  const bestAsk = toNum(asks[0]?.[0])
  const bidDepth = bids.slice(0, 10).reduce((sum: number, item: any) => sum + (toNum(item?.[1]) ?? 0), 0)
  const askDepth = asks.slice(0, 10).reduce((sum: number, item: any) => sum + (toNum(item?.[1]) ?? 0), 0)
  const spreadBps = bestBid && bestAsk ? ((bestAsk - bestBid) / ((bestAsk + bestBid) / 2)) * 10_000 : null
  const imbalance = bidDepth + askDepth > 0 ? (bidDepth - askDepth) / (bidDepth + askDepth) : null
  if (bestBid === null && bestAsk === null && spreadBps === null) return null
  return { bestBid, bestAsk, spreadBps, bidDepth, askDepth, imbalance }
}

export default function TradingView({
  symbol: symbolProp,
  allowSymbolSelect = true,
  titleOverride: titleOverrideProp,
  refreshMs: refreshMsProp = 60000,
  onSymbolChange,
}: TradingViewProps) {
  const [timeframe, setTimeframe] = useState('1h')
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [data, setData] = useState<KlinePoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastPrice, setLastPrice] = useState<number | null>(null)
  const [lastUpdate, setLastUpdate] = useState<string | null>(null)
  const [range, setRange] = useState<RangeData | null>(null)
  const [symbols, setSymbols] = useState<string[]>([])
  const [decisionView, setDecisionView] = useState<DecisionView | null>(null)
  const [forecastPoints, setForecastPoints] = useState<ForecastPoint[]>([])
  const [orderbook, setOrderbook] = useState<OrderbookMeta | null>(null)
  const [fixedSymbol, setFixedSymbol] = useState<string | null>(null)
  const [allowSelect, setAllowSelect] = useState<boolean>(true)
  const [titleOverride, setTitleOverride] = useState<string | null>(null)
  const [refreshMs, setRefreshMs] = useState<number>(60000)

  useEffect(() => {
    setFixedSymbol(symbolProp || null)
    setAllowSelect(allowSymbolSelect)
    setTitleOverride(titleOverrideProp || null)
    setRefreshMs(refreshMsProp)
    if (symbolProp) setSymbol(symbolProp)
  }, [symbolProp, allowSymbolSelect, titleOverrideProp, refreshMsProp])

  useEffect(() => {
    let cancelled = false
    const normalized = normalizeSymbol(fixedSymbol || symbol)

    const fetchChartData = async () => {
      setLoading(true)
      setError(null)
      try {
        const base = getApiBase()
        const [klineRes, rangeRes, forecastRes, decisionRes, orderbookRes] = await Promise.all([
          fetch(`${base}/api/market/kline?symbol=${normalized}&tf=${timeframe}&limit=120`),
          fetch(`${base}/api/market/ranges?symbol=${normalized}`),
          fetch(`${base}/api/market/forecast/${normalized}`),
          fetch(`${base}/api/signals/${normalized}/decision-view?mode=live`),
          fetch(`${base}/api/market/orderbook/${normalized}?limit=20`),
        ])
        if (cancelled) return
        if (!klineRes.ok) throw new Error('Błąd pobierania świec')

        const klineJson = await klineRes.json()
        const sorted = (klineJson.data || [])
          .map((item: any) => ({
            timestamp: parseTimestamp(item?.timestamp ?? item?.open_time ?? item?.time),
            open: toNum(item?.open),
            high: toNum(item?.high),
            low: toNum(item?.low),
            close: toNum(item?.close),
            volume: toNum(item?.volume) ?? 0,
          }))
          .filter((item: any) => item.open !== null && item.high !== null && item.low !== null && item.close !== null)
          .map((item: any) => ({
            timestamp: item.timestamp,
            open: item.open as number,
            high: item.high as number,
            low: item.low as number,
            close: item.close as number,
            volume: item.volume as number,
          }))
          .sort((a: KlinePoint, b: KlinePoint) => a.timestamp - b.timestamp)

        const rangeJson = rangeRes.ok ? await rangeRes.json() : null
        const forecastJson = forecastRes.ok ? await forecastRes.json() : null
        const decisionJson = decisionRes.ok ? await decisionRes.json() : null
        const orderbookJson = orderbookRes.ok ? await orderbookRes.json() : null
        const last = sorted[sorted.length - 1] ?? null

        if (!cancelled) {
          setData(sorted)
          setRange((rangeJson?.data?.[0] || null) as RangeData | null)
          setDecisionView((decisionJson?.data || null) as DecisionView | null)
          setForecastPoints(buildForecastPoints(forecastJson, timeframe, last?.timestamp ?? Date.now(), last?.close ?? null))
          setOrderbook(buildOrderbookMeta(orderbookJson))
          setLastPrice(last?.close ?? null)
          setLastUpdate(new Date().toLocaleTimeString('pl-PL'))
        }
      } catch {
        if (!cancelled) setError('Nie udało się pobrać danych wykresu z Binance/backendu')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchChartData()
    const interval = window.setInterval(fetchChartData, refreshMs)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [fixedSymbol, refreshMs, symbol, timeframe])

  useEffect(() => {
    const fetchSymbols = async () => {
      try {
        const base = getApiBase()
        const response = await fetch(`${base}/api/market/summary`)
        if (!response.ok) return
        const payload = await response.json()
        const nextSymbols = (payload.data || []).map((item: any) => item.symbol)
        setSymbols(nextSymbols)
        if (!fixedSymbol && nextSymbols.length > 0 && !nextSymbols.includes(symbol)) {
          setSymbol(nextSymbols[0])
        }
      } catch {
        // brak listy symboli nie blokuje wykresu
      }
    }
    fetchSymbols()
  }, [fixedSymbol, symbol])

  const displayTitle = useMemo(() => {
    if (titleOverride) return titleOverride
    return `Wykres ${fixedSymbol || symbol}`
  }, [fixedSymbol, symbol, titleOverride])

  const headlineAction = decisionView?.recommended_action_label || decisionView?.final_signal || 'CZEKAJ'
  const blockers = Array.isArray(decisionView?.blockers) ? decisionView.blockers : []
  const confidencePct = decisionView?.final_confidence != null
    ? (decisionView.final_confidence <= 1 ? decisionView.final_confidence * 100 : decisionView.final_confidence)
    : null

  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card terminal-card">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">{displayTitle}</h2>
          <div className="flex flex-wrap items-center gap-4 mt-1">
            <span className="text-2xl font-bold text-rldc-green-primary">{formatPrice(lastPrice)}</span>
            <span className="text-sm text-slate-400">Ostatnia aktualizacja: {lastUpdate || '--'}</span>
            <span className="text-sm text-slate-300">Decyzja: <span className="font-semibold">{headlineAction}</span></span>
            {confidencePct !== null && (
              <span className="text-sm text-slate-300">Pewność: {confidencePct.toFixed(1)}%</span>
            )}
          </div>
          <div className="text-sm text-slate-400 mt-2 max-w-4xl">
            {decisionView?.plain_explanation || decisionView?.final_signal_reason || range?.comment || 'Wykres pokazuje kanoniczne świece OHLC, wolumen, forecast i zakresy BUY/SELL z backendu.'}
          </div>
          {blockers.length > 0 && (
            <div className="text-xs text-amber-300 mt-2">Blokery: {blockers.join(', ')}</div>
          )}
        </div>

        <div className="flex space-x-2 items-center flex-wrap justify-end">
          {allowSelect && (
            <select
              title="Wybór symbolu"
              value={symbol}
              onChange={(event) => {
                const next = event.target.value
                setSymbol(next)
                onSymbolChange?.(normalizeSymbol(next))
              }}
              className="bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 text-xs rounded px-2 py-1"
            >
              {symbols.map((item) => (
                <option key={item} value={item}>{item}</option>
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

      <div className="rldc-chart bg-[#0b121a] border border-rldc-dark-border/60 rounded-lg p-3">
        {loading && <div className="text-sm text-slate-400 px-2 py-2">Ładowanie świec, wolumenu i forecastu...</div>}
        {error && <div className="text-sm text-rldc-red-primary px-2 py-2">{error}</div>}
        {!loading && !error && (
          <BinanceStyleChart
            candles={data}
            forecastPoints={forecastPoints}
            range={range}
            indicators={decisionView?.indicators as Record<string, number | string | null | undefined> | null}
            horizons={decisionView?.horizons || null}
            orderbook={orderbook}
            chartHeight={320}
            rsiHeight={74}
            emptyMessage={`Brak danych świecowych dla ${fixedSymbol || symbol}`}
          />
        )}
      </div>

      <div className="mt-3 text-xs text-slate-500">
        Źródło prawdy: Binance OHLC/orderbook + kanoniczny decision-view + backend forecast/ranges. Dane jakości: {decisionView?.data_quality || '--'}.
      </div>
    </div>
  )
}
