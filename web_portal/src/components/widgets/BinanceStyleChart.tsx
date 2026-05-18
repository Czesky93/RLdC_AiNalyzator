'use client'

import {
    CandlestickSeries,
    ColorType,
    createChart,
    CrosshairMode,
    HistogramSeries,
    LineSeries,
    LineStyle,
} from 'lightweight-charts'
import { useEffect, useMemo, useRef } from 'react'

type CandlePoint = {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

type ForecastPoint = {
  timestamp: number
  value: number
}

type RangeZone = {
  buy_low?: number | null
  buy_high?: number | null
  sell_low?: number | null
  sell_high?: number | null
  buy_target?: number | null
  sell_target?: number | null
  comment?: string | null
}

type DecisionIndicators = {
  rsi?: number | null
  ema20?: number | null
  ema50?: number | null
  atr?: number | null
  adx?: number | null
  stoch_k?: number | null
  volume_ratio?: number | null
  macd_hist?: number | null
  trend?: string | null
  spread_bps?: number | null
  orderbook_imbalance?: number | null
  bb_upper?: number | null
  bb_lower?: number | null
  fib_382?: number | null
  fib_618?: number | null
}

type HorizonMap = Record<string, {
  direction?: string | null
  projected_pct?: number | null
  forecast_price?: number | null
}>

type OrderbookMeta = {
  bestBid?: number | null
  bestAsk?: number | null
  spreadBps?: number | null
  bidDepth?: number | null
  askDepth?: number | null
  imbalance?: number | null
}

interface BinanceStyleChartProps {
  candles: CandlePoint[]
  forecastPoints?: ForecastPoint[]
  range?: RangeZone | null
  indicators?: DecisionIndicators | null
  horizons?: HorizonMap | null
  orderbook?: OrderbookMeta | null
  chartHeight?: number
  rsiHeight?: number
  className?: string
  emptyMessage?: string
}

function calcEma(closes: number[], period: number): Array<number | undefined> {
  const alpha = 2 / (period + 1)
  const output: Array<number | undefined> = Array(closes.length).fill(undefined)
  let ema: number | undefined
  for (let index = 0; index < closes.length; index += 1) {
    if (ema === undefined) {
      if (index >= period - 1) {
        ema = closes.slice(0, period).reduce((sum, value) => sum + value, 0) / period
      }
    } else {
      ema = closes[index] * alpha + ema * (1 - alpha)
    }
    output[index] = ema
  }
  return output
}

function calcRsi(closes: number[], period = 14): Array<number | undefined> {
  const output: Array<number | undefined> = Array(closes.length).fill(undefined)
  for (let index = period; index < closes.length; index += 1) {
    let gains = 0
    let losses = 0
    for (let cursor = index - period + 1; cursor <= index; cursor += 1) {
      const diff = closes[cursor] - closes[cursor - 1]
      if (diff > 0) gains += diff
      else losses += -diff
    }
    const rs = losses === 0 ? 100 : gains / losses
    output[index] = 100 - 100 / (1 + rs)
  }
  return output
}

function toChartTime(timestamp: number) {
  return Math.floor(timestamp / 1000) as never
}

function formatPrice(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--'
  const abs = Math.abs(value)
  const digits = abs < 0.01 ? 8 : abs < 1 ? 5 : abs < 100 ? 4 : 2
  return value.toLocaleString('pl-PL', {
    minimumFractionDigits: Math.min(2, digits),
    maximumFractionDigits: digits,
  })
}

function formatMetric(value: number | null | undefined, digits = 2, suffix = '') {
  if (value == null || !Number.isFinite(value)) return '--'
  return `${value.toLocaleString('pl-PL', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}${suffix}`
}

function levelColor(key: string) {
  if (key.startsWith('buy') || key.startsWith('fib')) return '#16f2a3'
  if (key.startsWith('sell')) return '#ef4444'
  return '#60a5fa'
}

function chartHeightClass(height: number) {
  if (height === 220) return 'h-[220px]'
  if (height === 320) return 'h-[320px]'
  return 'h-[320px]'
}

function rsiHeightClass(height: number) {
  if (height === 60) return 'h-[60px]'
  if (height === 72) return 'h-[72px]'
  if (height === 74) return 'h-[74px]'
  return 'h-[72px]'
}

export default function BinanceStyleChart({
  candles,
  forecastPoints = [],
  range,
  indicators,
  horizons,
  orderbook,
  chartHeight = 320,
  rsiHeight = 72,
  className = '',
  emptyMessage = 'Brak danych świecowych do analizy',
}: BinanceStyleChartProps) {
  const mainRef = useRef<HTMLDivElement | null>(null)
  const rsiRef = useRef<HTMLDivElement | null>(null)

  const sortedCandles = useMemo(
    () => [...candles].filter((item) => Number.isFinite(item.close)).sort((a, b) => a.timestamp - b.timestamp),
    [candles],
  )
  const closes = useMemo(() => sortedCandles.map((item) => item.close), [sortedCandles])
  const ema20 = useMemo(() => calcEma(closes, 20), [closes])
  const ema50 = useMemo(() => calcEma(closes, 50), [closes])
  const rsiValues = useMemo(() => calcRsi(closes, 14), [closes])
  const lastCandle = sortedCandles[sortedCandles.length - 1]
  const lastRsi = [...rsiValues].reverse().find((value) => value !== undefined) ?? null

  useEffect(() => {
    if (!mainRef.current || !rsiRef.current || sortedCandles.length < 2) return undefined

    const mainChart = createChart(mainRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b121a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.45)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.45)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(51, 65, 85, 0.7)',
        scaleMargins: { top: 0.08, bottom: 0.22 },
      },
      timeScale: {
        borderColor: 'rgba(51, 65, 85, 0.7)',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: CrosshairMode.MagnetOHLC,
      },
      handleScroll: true,
      handleScale: true,
    })

    const candleSeries = mainChart.addSeries(CandlestickSeries, {
      upColor: '#2EBD85',
      downColor: '#F6465D',
      borderVisible: false,
      wickUpColor: '#2EBD85',
      wickDownColor: '#F6465D',
      priceLineVisible: true,
      lastValueVisible: true,
    })

    const volumeSeries = mainChart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    mainChart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
      borderVisible: false,
    })

    const ema20Series = mainChart.addSeries(LineSeries, {
      color: '#f0b90b',
      lineWidth: 2,
      lastValueVisible: false,
      priceLineVisible: false,
    })
    const ema50Series = mainChart.addSeries(LineSeries, {
      color: '#7c3aed',
      lineWidth: 2,
      lastValueVisible: false,
      priceLineVisible: false,
    })
    const forecastSeries = mainChart.addSeries(LineSeries, {
      color: '#50a7ff',
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      lastValueVisible: false,
      priceLineVisible: false,
    })

    candleSeries.setData(
      sortedCandles.map((item) => ({
        time: toChartTime(item.timestamp),
        open: item.open,
        high: item.high,
        low: item.low,
        close: item.close,
      })),
    )

    volumeSeries.setData(
      sortedCandles.map((item) => ({
        time: toChartTime(item.timestamp),
        value: item.volume ?? 0,
        color: item.close >= item.open ? 'rgba(46, 189, 133, 0.45)' : 'rgba(246, 70, 93, 0.45)',
      })),
    )

    ema20Series.setData(
      sortedCandles
        .map((item, index) => ({
          time: toChartTime(item.timestamp),
          value: ema20[index],
        }))
        .filter((item) => item.value !== undefined) as Array<{ time: never; value: number }>,
    )

    ema50Series.setData(
      sortedCandles
        .map((item, index) => ({
          time: toChartTime(item.timestamp),
          value: ema50[index],
        }))
        .filter((item) => item.value !== undefined) as Array<{ time: never; value: number }>,
    )

    forecastSeries.setData(
      forecastPoints
        .filter((item) => Number.isFinite(item.value))
        .sort((a, b) => a.timestamp - b.timestamp)
        .map((item) => ({ time: toChartTime(item.timestamp), value: item.value })),
    )

    const levelEntries: Array<[string, number | null | undefined]> = [
      ['buy_low', range?.buy_low],
      ['buy_high', range?.buy_high],
      ['buy_target', range?.buy_target],
      ['sell_low', range?.sell_low],
      ['sell_high', range?.sell_high],
      ['sell_target', range?.sell_target],
      ['fib_382', indicators?.fib_382],
      ['fib_618', indicators?.fib_618],
    ]
    levelEntries.forEach(([key, value]) => {
      if (value == null || !Number.isFinite(value)) return
      candleSeries.createPriceLine({
        price: value,
        color: levelColor(key),
        lineStyle: key.includes('target') ? LineStyle.Dashed : LineStyle.Dotted,
        lineWidth: 1,
        axisLabelVisible: true,
        title: key.replace('_', ' ').toUpperCase(),
      })
    })

    const resize = () => {
      if (!mainRef.current || !rsiRef.current) return
      const width = mainRef.current.clientWidth
      if (width > 0) mainChart.resize(width, chartHeight)
      const rsiWidth = rsiRef.current.clientWidth
      if (rsiWidth > 0) rsiChart.resize(rsiWidth, rsiHeight)
    }

    const rsiChart = createChart(rsiRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b121a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.35)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.35)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(51, 65, 85, 0.7)',
        scaleMargins: { top: 0.12, bottom: 0.1 },
      },
      timeScale: {
        borderColor: 'rgba(51, 65, 85, 0.7)',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
      },
      handleScroll: false,
      handleScale: false,
    })

    const rsiSeries = rsiChart.addSeries(LineSeries, {
      color: '#a78bfa',
      lineWidth: 2,
      lastValueVisible: false,
      priceLineVisible: false,
    })
    rsiSeries.setData(
      sortedCandles
        .map((item, index) => ({ time: toChartTime(item.timestamp), value: rsiValues[index] }))
        .filter((item) => item.value !== undefined) as Array<{ time: never; value: number }>,
    )
    rsiSeries.createPriceLine({
      price: 70,
      color: '#ef4444',
      lineStyle: LineStyle.Dotted,
      lineWidth: 1,
      axisLabelVisible: true,
      title: 'RSI 70',
    })
    rsiSeries.createPriceLine({
      price: 30,
      color: '#16f2a3',
      lineStyle: LineStyle.Dotted,
      lineWidth: 1,
      axisLabelVisible: true,
      title: 'RSI 30',
    })
    rsiChart.priceScale('right').applyOptions({ autoScale: false, mode: 0, invertScale: false })
    rsiChart.timeScale().fitContent()
    mainChart.timeScale().fitContent()
    resize()

    const observer = new ResizeObserver(resize)
    observer.observe(mainRef.current)
    observer.observe(rsiRef.current)

    return () => {
      observer.disconnect()
      mainChart.remove()
      rsiChart.remove()
    }
  }, [chartHeight, ema20, ema50, forecastPoints, indicators, range, rsiHeight, rsiValues, sortedCandles])

  const infoChips = useMemo(() => {
    const chips = [
      indicators?.trend ? `Trend: ${String(indicators.trend).toUpperCase()}` : null,
      indicators?.rsi != null ? `RSI: ${formatMetric(indicators.rsi, 1)}` : lastRsi != null ? `RSI: ${formatMetric(lastRsi, 1)}` : null,
      indicators?.atr != null ? `ATR: ${formatMetric(indicators.atr, 4)}` : null,
      indicators?.adx != null ? `ADX: ${formatMetric(indicators.adx, 1)}` : null,
      indicators?.stoch_k != null ? `Stoch K: ${formatMetric(indicators.stoch_k, 1)}` : null,
      indicators?.volume_ratio != null ? `Wolumen/SMA20: ${formatMetric(indicators.volume_ratio, 2)}x` : null,
      indicators?.macd_hist != null ? `MACD hist: ${formatMetric(indicators.macd_hist, 4)}` : null,
      orderbook?.spreadBps != null ? `Spread: ${formatMetric(orderbook.spreadBps, 1, ' bps')}` : indicators?.spread_bps != null ? `Spread: ${formatMetric(indicators.spread_bps, 1, ' bps')}` : null,
      orderbook?.imbalance != null ? `Orderbook: ${formatMetric(orderbook.imbalance, 2)}` : indicators?.orderbook_imbalance != null ? `Orderbook: ${formatMetric(indicators.orderbook_imbalance, 2)}` : null,
      horizons?.['1h']?.direction ? `1h: ${String(horizons['1h'].direction).toLowerCase()}` : null,
      horizons?.['4h']?.direction ? `4h: ${String(horizons['4h'].direction).toLowerCase()}` : null,
      horizons?.['24h']?.direction ? `24h: ${String(horizons['24h'].direction).toLowerCase()}` : null,
    ]
    return chips.filter(Boolean) as string[]
  }, [horizons, indicators, lastRsi, orderbook])

  if (sortedCandles.length < 2) {
    return <div className="text-xs text-slate-500 py-6 text-center">{emptyMessage}</div>
  }

  return (
    <div className={className}>
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2 mb-3">
        <div className="rounded border border-rldc-dark-border/60 bg-[#0b121a] px-3 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">O / H / L / C</div>
          <div className="text-xs font-mono text-slate-200">
            {formatPrice(lastCandle?.open)} / {formatPrice(lastCandle?.high)} / {formatPrice(lastCandle?.low)} / {formatPrice(lastCandle?.close)}
          </div>
        </div>
        <div className="rounded border border-rldc-dark-border/60 bg-[#0b121a] px-3 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Wolumen</div>
          <div className="text-xs font-mono text-slate-200">{formatMetric(lastCandle?.volume, 2)}</div>
        </div>
        <div className="rounded border border-rldc-dark-border/60 bg-[#0b121a] px-3 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">BUY / SELL</div>
          <div className="text-xs font-mono text-slate-200">
            {range?.buy_low != null || range?.buy_high != null ? `${formatPrice(range?.buy_low)}–${formatPrice(range?.buy_high)}` : '--'}
            {' / '}
            {range?.sell_low != null || range?.sell_high != null ? `${formatPrice(range?.sell_low)}–${formatPrice(range?.sell_high)}` : '--'}
          </div>
        </div>
        <div className="rounded border border-rldc-dark-border/60 bg-[#0b121a] px-3 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Targety</div>
          <div className="text-xs font-mono text-slate-200">
            {formatPrice(range?.buy_target)} / {formatPrice(range?.sell_target)}
          </div>
        </div>
        <div className="rounded border border-rldc-dark-border/60 bg-[#0b121a] px-3 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Bid / Ask</div>
          <div className="text-xs font-mono text-slate-200">
            {formatPrice(orderbook?.bestBid)} / {formatPrice(orderbook?.bestAsk)}
          </div>
        </div>
        <div className="rounded border border-rldc-dark-border/60 bg-[#0b121a] px-3 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Komentarz zakresu</div>
          <div className="text-xs text-slate-300 line-clamp-2">{range?.comment || 'Brak komentarza zakresu.'}</div>
        </div>
      </div>

      <div className="rounded border border-rldc-dark-border/60 bg-[#0b121a] p-2">
        <div ref={mainRef} className={`w-full ${chartHeightClass(chartHeight)}`} />
        <div className="mt-2 border-t border-rldc-dark-border/40 pt-2">
          <div className="mb-1 flex items-center justify-between px-1">
            <span className="text-[10px] uppercase tracking-widest text-slate-500">RSI (14)</span>
            <span className={`text-[10px] font-mono font-semibold ${lastRsi == null ? 'text-slate-500' : lastRsi < 30 ? 'text-rldc-green-primary' : lastRsi > 70 ? 'text-rldc-red-primary' : 'text-slate-300'}`}>
              {lastRsi == null ? '--' : Math.round(lastRsi)}
            </span>
          </div>
          <div ref={rsiRef} className={`w-full ${rsiHeightClass(rsiHeight)}`} />
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        <span className="rounded-full border border-rldc-dark-border/60 bg-[#0b121a] px-2 py-1 text-[10px] text-slate-400">Świece OHLC</span>
        <span className="rounded-full border border-rldc-dark-border/60 bg-[#0b121a] px-2 py-1 text-[10px] text-slate-400">EMA 20</span>
        <span className="rounded-full border border-rldc-dark-border/60 bg-[#0b121a] px-2 py-1 text-[10px] text-slate-400">EMA 50</span>
        <span className="rounded-full border border-rldc-dark-border/60 bg-[#0b121a] px-2 py-1 text-[10px] text-slate-400">Wolumen</span>
        <span className="rounded-full border border-rldc-dark-border/60 bg-[#0b121a] px-2 py-1 text-[10px] text-slate-400">Forecast</span>
        {infoChips.map((chip) => (
          <span key={chip} className="rounded-full border border-rldc-dark-border/60 bg-[#0b121a] px-2 py-1 text-[10px] text-slate-300">
            {chip}
          </span>
        ))}
      </div>
    </div>
  )
}
