'use client'

import React, { useEffect, useState } from 'react'
import { ADMIN_TOKEN_STORAGE_KEY, getAdminToken, getApiBase, withAdminToken } from '../lib/api'
import DecisionRisk from './widgets/DecisionRisk'
import DecisionsRiskPanel from './widgets/DecisionsRiskPanel'
import EquityCurve from './widgets/EquityCurve'
import MarketInsights from './widgets/MarketInsights'
import OpenOrders from './widgets/OpenOrders'
import TradingView from './widgets/TradingView'

interface MainContentProps {
  activeView: string
  tradingMode: 'live' | 'demo'
}

/**
 * useFetch — pobiera dane z API lazily.
 * Zwraca lastUpdated (znacznik czasu) i staleSec (ile sekund temu odświeżono).
 */
function useFetch<T>(path: string, refreshMs: number = 0) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!path) {
      setData(null)
      setLoading(false)
      setError(null)
      return () => { cancelled = true }
    }
    const buildUrl = () => {
      const base = getApiBase()
      return path.startsWith('http') ? path : `${base}${path}`
    }
    const fetchData = async () => {
      try {
        const url = buildUrl()
        const res = await fetch(url)
        if (!res.ok) {
          let detail = ''
          try { detail = (await res.json()).detail || '' } catch { /* ignore */ }
          throw new Error(`HTTP ${res.status}${detail ? ': ' + detail : ''}`)
        }
        const json = await res.json()
        if (!cancelled) {
          setData(json)
          setLastUpdated(new Date())
          setError(null)
        }
      } catch (err: any) {
        if (!cancelled) {
          const msg = err?.message || 'Błąd połączenia'
          setError(msg.startsWith('HTTP') ? `Błąd serwera (${msg})` : `Brak połączenia: ${msg}`)
          console.error('[useFetch]', path, err)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchData()
    const interval = refreshMs > 0 ? setInterval(fetchData, refreshMs) : null
    return () => {
      cancelled = true
      if (interval) clearInterval(interval)
    }
  }, [path, refreshMs])

  return { data, loading, error, lastUpdated }
}

/** Przedstawia czas ostatniego odświeżenia i status synchronizacji. */
function DataStatus({
  lastUpdated,
  loading,
  error,
  refreshMs,
}: {
  lastUpdated: Date | null
  loading: boolean
  error: string | null
  refreshMs?: number
}) {
  const [, forceRender] = useState(0)
  // odświeżaj wyświetlany czas co 10s
  useEffect(() => {
    const t = setInterval(() => forceRender((n) => n + 1), 10000)
    return () => clearInterval(t)
  }, [])

  if (loading && !lastUpdated) return null

  const secondsAgo = lastUpdated ? Math.floor((Date.now() - lastUpdated.getTime()) / 1000) : null
  const isStale = secondsAgo !== null && refreshMs && secondsAgo > refreshMs / 1000 * 2.5
  const timeLabel = secondsAgo === null
    ? 'brak danych'
    : secondsAgo < 60
    ? `${secondsAgo}s temu`
    : `${Math.floor(secondsAgo / 60)} min temu`

  if (error) {
    return (
      <div className="flex items-center gap-1.5 text-[10px] text-rldc-red-primary">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-rldc-red-primary animate-pulse" />
        Synchronizacja zatrzymana
      </div>
    )
  }
  if (isStale) {
    return (
      <div className="flex items-center gap-1.5 text-[10px] text-yellow-400">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-yellow-400" />
        Dane mogą być nieaktualne · {timeLabel}
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
      <span className="inline-block w-1.5 h-1.5 rounded-full bg-rldc-green-primary" />
      Odświeżono {timeLabel}
    </div>
  )
}

/** Jednolity komunikat dla pustych / nieaktywnych sekcji. */
function EmptyState({
  reason = 'no-data',
  detail,
}: {
  reason?: 'no-data' | 'not-connected' | 'sync-stopped'
  detail?: string
}) {
  const messages: Record<string, { icon: string; title: string; desc: string }> = {
    'no-data': {
      icon: '📭',
      title: 'Brak danych',
      desc: 'System nie zwrócił żadnych rekordów. Spróbuj ponownie lub sprawdź, czy bot jest aktywny.',
    },
    'not-connected': {
      icon: '🔌',
      title: 'Ten widok nie jest jeszcze aktywny',
      desc: 'Moduł nie jest podłączony do backendu. Zostanie włączony w kolejnej wersji.',
    },
    'sync-stopped': {
      icon: '⏸',
      title: 'Synchronizacja zatrzymana',
      desc: detail || 'Nie udało się pobrać nowych danych. Sprawdź połączenie z backendem.',
    },
  }
  const m = messages[reason]
  return (
    <div className="bg-rldc-dark-card rounded-lg p-8 text-center border border-rldc-dark-border/60">
      <div className="text-3xl mb-3">{m.icon}</div>
      <div className="text-base font-semibold text-slate-200 mb-1">{m.title}</div>
      <div className="text-sm text-slate-400 max-w-md mx-auto">{m.desc}</div>
    </div>
  )
}

/** Ocenia realność celu użytkownika na podstawie odległości % i RSI/trendu. */
function assessGoalRealism(pctNeeded: number, trend?: string, rsi?: number | null): {
  label: string
  color: string
  explanation: string
} {
  const abs = Math.abs(pctNeeded)
  if (abs < 5) return { label: 'Bardzo bliski', color: 'text-rldc-green-primary', explanation: 'Cena jest bardzo blisko celu — ruch jest minimalny.' }
  if (abs < 15) {
    const trendOk = trend === 'WZROSTOWY' && pctNeeded > 0
    return trendOk
      ? { label: 'Realny', color: 'text-rldc-green-primary', explanation: 'Cel jest w zasięgu, a trend wspiera kierunek ruchu.' }
      : { label: 'Możliwy', color: 'text-yellow-400', explanation: 'Cel jest w zasięgu, ale trend nie potwierdza jeszcze ruchu.' }
  }
  if (abs < 40) return { label: 'Trudny', color: 'text-yellow-400', explanation: 'Potrzebny jest istotny ruch cenowy. Cel możliwy w średnim terminie.' }
  return { label: 'Mało realny', color: 'text-rldc-red-primary', explanation: 'Wymagany ruch jest bardzo duży. Cel może być osiągnięty tylko w długim terminie.' }
}

/** Prosta obsługa celów użytkownika w localStorage. */
const GOALS_KEY = 'rldc_user_goals_v1'
type UserGoal = { targetEur: number; label?: string; setAt: string }
function loadGoals(): Record<string, UserGoal> {
  if (typeof window === 'undefined') return {}
  try { return JSON.parse(localStorage.getItem(GOALS_KEY) || '{}') } catch { return {} }
}
function saveGoal(symbol: string, goal: UserGoal) {
  if (typeof window === 'undefined') return
  const g = loadGoals()
  g[symbol] = goal
  localStorage.setItem(GOALS_KEY, JSON.stringify(g))
  // Synchronizacja z backendem (fire-and-forget)
  fetch(`${getApiBase()}/api/positions/goal/${symbol}`, {
    method: 'PUT',
    headers: withAdminToken({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ target_eur: goal.targetEur, label: goal.label || '' }),
  }).catch(() => { /* ignoruj błąd - localStorage to nadal źródło prawdy w UI */ })
}
function removeGoal(symbol: string) {
  if (typeof window === 'undefined') return
  const g = loadGoals()
  delete g[symbol]
  localStorage.setItem(GOALS_KEY, JSON.stringify(g))
  // Synchronizacja z backendem (fire-and-forget)
  fetch(`${getApiBase()}/api/positions/goal/${symbol}`, {
    method: 'DELETE',
    headers: withAdminToken(),
  }).catch(() => {})
}

/**
 * buildMainRecommendation — buduje rekomendację z kanonicznego modelu decision-view gdy dostępny,
 * albo z lokalnych komponentów jako fallback.
 * ZASADA: final_signal z backendu jest autorytetem. Nie wolno anulować decyzji SELL przez BUY.
 */
function buildMainRecommendation(
  card: any,
  latestSignal: any,
  forecast: any,
  hasPosition: boolean,
  decisionView?: any,   // kanoniczny model z /api/signals/{symbol}/decision-view
): { decision: string; reasons: string[]; color: string; bg: string; urgency: 'high' | 'medium' | 'low' } {

  // ── Kanoniczny model z backendu — używaj gdy dostępny ──────────────────────
  if (decisionView && decisionView.final_signal) {
    const fs = decisionView.final_signal as string        // BUY | SELL | WAIT | HOLD | NO_TRADE
    const reason = decisionView.final_signal_reason as string || ''
    const conf = decisionView.final_confidence != null
      ? `${Math.round((decisionView.final_confidence as number) * 100)}% pewność`
      : ''
    const dq = decisionView.data_quality as string || ''
    const warnings: string[] = decisionView.warnings || []
    const blockers: string[] = decisionView.blockers || []

    const reasons: string[] = [reason]
    if (conf) reasons.push(conf)
    if (dq === 'stale') reasons.push(`⚠ Dane stare (${decisionView.data_age_seconds}s)`)
    if (dq === 'degraded') reasons.push(`Dane częściowo aktualne`)
    if (warnings.length > 0) reasons.push(warnings[0])
    if (blockers.length > 0 && fs !== 'BUY') reasons.push(blockers[0])

    // Mapa final_signal → UI
    if (fs === 'BUY' && !hasPosition) {
      return {
        decision: 'KUP TERAZ',
        reasons: reasons.slice(0, 4),
        color: 'text-rldc-green-primary',
        bg: 'bg-rldc-green-primary/10 border-rldc-green-primary/30',
        urgency: 'high',
      }
    }
    if (fs === 'BUY' && hasPosition) {
      return {
        decision: 'TRZYMAJ',
        reasons: ['Pozycja już otwarta — sygnał kupna potwierdza trend', ...reasons.slice(0, 3)],
        color: 'text-rldc-teal-primary',
        bg: 'bg-rldc-teal-primary/10 border-rldc-teal-primary/30',
        urgency: 'low',
      }
    }
    if (fs === 'SELL' && hasPosition) {
      return {
        decision: 'ZAMKNIJ POZYCJĘ',
        reasons: reasons.slice(0, 4),
        color: 'text-rldc-red-primary',
        bg: 'bg-rldc-red-primary/10 border-rldc-red-primary/30',
        urgency: 'high',
      }
    }
    if (fs === 'SELL' && !hasPosition) {
      return {
        decision: 'NIE WCHODŹ',
        reasons: ['Sygnał sprzedaży bez otwartej pozycji — spot trading', ...reasons.slice(0, 3)],
        color: 'text-rldc-red-primary',
        bg: 'bg-rldc-red-primary/10 border-rldc-red-primary/30',
        urgency: 'medium',
      }
    }
    if (fs === 'HOLD' && hasPosition) {
      const pnlPct: number = card?.pnl_pct ?? 0
      if (pnlPct > 5) {
        return {
          decision: 'SPRZEDAJ CZĘŚĆ',
          reasons: [`Pozycja na +${pnlPct.toFixed(1)}% — warto zabezpieczyć zysk`, ...reasons.slice(0, 3)],
          color: 'text-orange-400',
          bg: 'bg-orange-400/10 border-orange-400/30',
          urgency: 'medium',
        }
      }
      return {
        decision: 'TRZYMAJ',
        reasons: reasons.slice(0, 4),
        color: 'text-rldc-teal-primary',
        bg: 'bg-rldc-teal-primary/10 border-rldc-teal-primary/30',
        urgency: 'low',
      }
    }
    if (fs === 'NO_TRADE' || fs === 'WAIT') {
      return {
        decision: 'POCZEKAJ',
        reasons: reasons.slice(0, 4),
        color: 'text-yellow-400',
        bg: 'bg-yellow-400/10 border-yellow-400/30',
        urgency: 'low',
      }
    }
  }

  // ── FALLBACK: lokalna heurystyka (bez decision-view z backendu) ───────────
  const f24 = (forecast as any)?.forecast_24h
  const f1h = (forecast as any)?.forecast_1h
  const sysDecision = ((card?.decision || '') as string).toUpperCase()
  const trend = (card?.trend || '') as string
  const rsi: number | null = card?.rsi ?? null
  const signalType = (latestSignal?.signal_type || '') as string
  const signalConf = Math.round((latestSignal?.confidence || 0) * 100)
  const pnlPct: number = card?.pnl_pct ?? 0

  const reasons: string[] = []
  if (signalType === 'BUY' && signalConf > 0) reasons.push(`Sygnał kupna z pewnością ${signalConf}%`)
  else if (signalType === 'SELL') reasons.push(`Sygnał sprzedaży z pewnością ${signalConf}%`)
  if (trend === 'WZROSTOWY') reasons.push('Trend wzrostowy (EMA20 > EMA50)')
  else if (trend === 'SPADKOWY') reasons.push('Trend spadkowy (EMA20 < EMA50)')
  if (rsi != null && rsi < 32) reasons.push(`RSI ${rsi} — strefa wyprzedania`)
  else if (rsi != null && rsi > 70) reasons.push(`RSI ${rsi} — strefa wykupowania`)
  if (f24) {
    const pct = f24.projected_pct != null ? ` (${f24.projected_pct > 0 ? '+' : ''}${(f24.projected_pct as number).toFixed(1)}%)` : ''
    reasons.push(`Prognoza 24h: ${f24.direction}${pct}`)
  }
  if (hasPosition && pnlPct > 5) reasons.push(`Pozycja na +${pnlPct.toFixed(1)}% — dobry zysk`)
  else if (hasPosition && pnlPct < -5) reasons.push(`Pozycja na ${pnlPct.toFixed(1)}% — obserwuj ryzyko`)

  let posScore = 0
  let negScore = 0
  if (trend === 'WZROSTOWY') posScore++
  else if (trend === 'SPADKOWY') negScore++
  if (rsi != null && rsi < 35) posScore++
  else if (rsi != null && rsi > 68) negScore++
  if (f24?.direction === 'WZROSTOWY') posScore++
  else if (f24?.direction === 'SPADKOWY') negScore++
  if (f1h?.direction === 'WZROSTOWY') posScore++
  else if (f1h?.direction === 'SPADKOWY') negScore++
  if (signalType === 'BUY') posScore += signalConf >= 70 ? 2 : 1
  else if (signalType === 'SELL') negScore += signalConf >= 70 ? 2 : 1
  if (sysDecision.includes('KUP') || sysDecision === 'BUY') posScore++
  else if (sysDecision.includes('SPRZEDAJ') || sysDecision.includes('ZAMKNIJ') || sysDecision === 'SELL') negScore++

  let decision = 'OBSERWUJ'
  let color = 'text-slate-400'
  let bg = 'bg-slate-500/10 border-slate-500/20'
  let urgency: 'high' | 'medium' | 'low' = 'low'

  if (hasPosition) {
    if (negScore >= 3) {
      decision = 'ZAMKNIJ POZYCJĘ'; color = 'text-rldc-red-primary'; bg = 'bg-rldc-red-primary/10 border-rldc-red-primary/30'; urgency = 'high'
    } else if (negScore >= 2 || (f24?.direction === 'SPADKOWY' && pnlPct > 2)) {
      decision = 'SPRZEDAJ CZĘŚĆ'; color = 'text-orange-400'; bg = 'bg-orange-400/10 border-orange-400/30'; urgency = 'medium'
    } else if (posScore >= 2) {
      decision = 'TRZYMAJ'; color = 'text-rldc-teal-primary'; bg = 'bg-rldc-teal-primary/10 border-rldc-teal-primary/30'; urgency = 'low'
    }
  } else {
    // WAŻNE: jeśli sygnał jest SELL, nie możemy pokazać BUY jako decyzji
    if (signalType === 'SELL') {
      decision = 'NIE WCHODŹ'; color = 'text-rldc-red-primary'; bg = 'bg-rldc-red-primary/10 border-rldc-red-primary/30'; urgency = 'medium'
    } else if (posScore >= 3) {
      decision = 'KUP TERAZ'; color = 'text-rldc-green-primary'; bg = 'bg-rldc-green-primary/10 border-rldc-green-primary/30'; urgency = 'high'
    } else if (posScore >= 2) {
      decision = 'KANDYDAT DO WEJŚCIA'; color = 'text-rldc-green-primary'; bg = 'bg-rldc-green-primary/5 border-rldc-green-primary/20'; urgency = 'medium'
    } else if (negScore >= 2) {
      decision = 'NIE WCHODŹ'; color = 'text-rldc-red-primary'; bg = 'bg-rldc-red-primary/10 border-rldc-red-primary/30'; urgency = 'medium'
    } else {
      decision = 'POCZEKAJ'; color = 'text-yellow-400'; bg = 'bg-yellow-400/10 border-yellow-400/30'
    }
  }

  return { decision, reasons: reasons.slice(0, 4), color, bg, urgency }
}

function SimpleTable({
  title,
  headers,
  rows,
  actions,
}: {
  title: string
  headers: string[]
  rows: React.ReactNode[][]
  actions?: React.ReactNode
}) {
  return (
    <div className="terminal-card rounded-lg p-4 border border-rldc-dark-border neon-card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
        {actions ? actions : <div className="text-[10px] uppercase tracking-widest terminal-muted">na żywo</div>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-[12px]">
          <thead>
            <tr className="border-b border-rldc-dark-border text-left text-[10px] uppercase tracking-widest text-slate-500">
              {headers.map((h) => (
                <th key={h} className="pb-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={idx} className="border-b border-rldc-dark-border/50 hover:bg-rldc-dark-hover transition">
                {row.map((cell, cidx) => (
                  <td key={cidx} className="py-2 text-slate-300">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ViewHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{title}</h1>
        <div className="px-3 py-1 bg-rldc-teal-primary/20 text-rldc-teal-primary rounded text-sm font-medium">
          Dane z API
        </div>
      </div>
      {description && <p className="text-sm text-slate-400 mt-1">{description}</p>}
    </div>
  )
}

/* ─────────────────────────────────────────────────
 *  SYMBOL DETAIL PANEL — pełny panel analizy symbolu
 *  Otwierany przez kliknięcie w symbol w KAŻDYM widoku
 * ───────────────────────────────────────────────── */

function ForecastChart({ symbol }: { symbol: string }) {
  const { data: klines } = useFetch<any>(`/api/market/kline?symbol=${symbol}&limit=60`, 30000)
  const { data: forecast } = useFetch<any>(`/api/market/forecast/${symbol}`, 60000)

  // Oblicz EMA pomocniczo
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

  // Oblicz RSI(14)
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

  const historyPoints: { t: string; price: number }[] = (klines?.data || []).map((k: any) => ({
    t: typeof k.timestamp === 'string' ? k.timestamp.slice(11, 16) : new Date(typeof k.timestamp === 'number' ? k.timestamp : 0).toISOString().slice(11, 16),
    price: typeof k.close === 'number' ? k.close : typeof k.price === 'number' ? k.price : null,
  })).filter((p: any) => p.price !== null)

  const forecastPoints: { t: string; forecast: number }[] = (forecast?.data || []).map((f: any) => ({
    t: typeof f.timestamp === 'string' ? f.timestamp.slice(11, 16) : String(f.timestamp || ''),
    forecast: typeof f.price === 'number' ? f.price : null,
  })).filter((p: any) => p.forecast !== null)

  if (historyPoints.length === 0) {
    return <div className="text-xs text-slate-500 py-4 text-center">Brak danych do wykresu</div>
  }

  const closes = historyPoints.map(p => p.price)
  const ema20vals = calcEma(closes, 20)
  const ema50vals = calcEma(closes, 50)
  const rsiVals = calcRsi(closes, 14)

  const allPrices = [
    ...closes,
    ...ema20vals.filter((v): v is number => v !== undefined),
    ...ema50vals.filter((v): v is number => v !== undefined),
    ...forecastPoints.map(p => p.forecast),
  ]
  const minP = Math.min(...allPrices) * 0.998
  const maxP = Math.max(...allPrices) * 1.002
  const fmt = (v: number) => v < 1 ? v.toFixed(6) : v < 100 ? v.toFixed(4) : v.toFixed(2)

  // Połączony zestaw danych: historia + prognoza + EMA
  const combined = [
    ...historyPoints.map((p, i) => ({
      t: p.t,
      price: p.price,
      ema20: ema20vals[i],
      ema50: ema50vals[i],
      forecast: undefined as number | undefined,
    })),
    ...(forecastPoints.length > 0
      ? [{ t: historyPoints[historyPoints.length - 1]?.t, price: historyPoints[historyPoints.length - 1]?.price, ema20: undefined, ema50: undefined, forecast: historyPoints[historyPoints.length - 1]?.price }]
      : []),
    ...forecastPoints.map(p => ({ t: p.t, price: undefined as number | undefined, ema20: undefined, ema50: undefined, forecast: p.forecast })),
  ]

  // Dane RSI (tylko historia)
  const rsiData = historyPoints.map((p, i) => ({ t: p.t, rsi: rsiVals[i] !== undefined ? Math.round(rsiVals[i]! * 10) / 10 : undefined }))
  const lastRsi = rsiVals.filter(v => v !== undefined).pop()

  const { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, ComposedChart, Area } =
    require('recharts')

  return (
    <div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={combined} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis dataKey="t" tick={{ fontSize: 9, fill: '#64748b' }} interval="preserveStartEnd" />
          <YAxis domain={[minP, maxP]} tick={{ fontSize: 9, fill: '#64748b' }} tickFormatter={fmt} width={58} />
          <Tooltip
            contentStyle={{ background: '#0f1923', border: '1px solid #1e2d3d', fontSize: 10 }}
            formatter={(val: any, name: string) => [
              val != null ? fmt(val) : '--',
              name === 'price' ? 'Cena' : name === 'ema20' ? 'EMA 20' : name === 'ema50' ? 'EMA 50' : 'Prognoza'
            ]}
          />
          {forecastPoints.length > 0 && (
            <ReferenceLine
              x={historyPoints[historyPoints.length - 1]?.t}
              stroke="#64748b"
              strokeDasharray="3 3"
              label={{ value: 'teraz', fill: '#64748b', fontSize: 9 }}
            />
          )}
          <Line type="monotone" dataKey="ema50" stroke="#7c3aed" dot={false} strokeWidth={1} connectNulls name="ema50" />
          <Line type="monotone" dataKey="ema20" stroke="#fbbf24" dot={false} strokeWidth={1} connectNulls name="ema20" />
          <Line type="monotone" dataKey="price" stroke="#00d4aa" dot={false} strokeWidth={1.5} connectNulls={false} name="price" />
          <Line type="monotone" dataKey="forecast" stroke="#f97316" dot={false} strokeWidth={1.5} strokeDasharray="4 4" connectNulls={false} name="forecast" />
        </LineChart>
      </ResponsiveContainer>

      {/* Mini RSI chart */}
      <div className="mt-1">
        <div className="flex items-center justify-between mb-0.5 px-1">
          <span className="text-[9px] text-slate-500 uppercase tracking-widest">RSI (14)</span>
          <span className={`text-[10px] font-mono font-bold ${lastRsi == null ? 'text-slate-500' : lastRsi < 30 ? 'text-rldc-green-primary' : lastRsi > 70 ? 'text-rldc-red-primary' : 'text-slate-300'}`}>
            {lastRsi != null ? Math.round(lastRsi) : '--'}
            {lastRsi != null && lastRsi < 30 ? ' (wyprzedanie)' : lastRsi != null && lastRsi > 70 ? ' (wykupienie)' : ''}
          </span>
        </div>
        <ResponsiveContainer width="100%" height={50}>
          <LineChart data={rsiData} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="t" hide />
            <YAxis domain={[0, 100]} tick={{ fontSize: 8, fill: '#64748b' }} width={30} tickCount={3} ticks={[30, 50, 70]} />
            <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="2 2" strokeWidth={0.8} />
            <ReferenceLine y={30} stroke="#22c55e" strokeDasharray="2 2" strokeWidth={0.8} />
            <Line type="monotone" dataKey="rsi" stroke="#a78bfa" dot={false} strokeWidth={1.2} connectNulls name="rsi" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Legenda wskaźników */}
      <div className="flex items-center gap-3 mt-1 px-1 flex-wrap">
        <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="inline-block w-3 h-0.5 bg-rldc-teal-primary"></span> Cena</span>
        <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="inline-block w-3 h-0.5 bg-yellow-400"></span> EMA 20</span>
        <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="inline-block w-3 h-0.5 bg-purple-500"></span> EMA 50</span>
        <span className="flex items-center gap-1 text-[9px] text-slate-500"><span className="inline-block w-3 h-0.5 bg-rldc-orange-primary" style={{backgroundImage:'repeating-linear-gradient(90deg,#f97316 0,#f97316 3px,transparent 3px,transparent 6px)'}}></span> Prognoza</span>
      </div>

      {forecastPoints.length === 0 && (
        <div className="text-[10px] text-slate-500 text-center mt-1">Prognoza niedostępna (AI offline lub brak danych)</div>
      )}
    </div>
  )
}

function SymbolDetailPanel({
  symbol,
  mode,
  onClose,
}: {
  symbol: string
  mode: 'demo' | 'live'
  onClose: () => void
}) {
  const { data: analysis, loading: analysisLoading, lastUpdated: analysisUpdated } = useFetch<any>(`/api/positions/analysis?mode=${mode}`, 15000)
  const { data: signals, lastUpdated: signalsUpdated } = useFetch<any>(`/api/signals/latest?limit=50`, 15000)
  const { data: ticker, loading: tickerLoading } = useFetch<any>(`/api/market/ticker/${symbol}`, 15000)
  const { data: accuracy } = useFetch<any>(`/api/market/forecast-accuracy/${symbol}?limit=20`, 60000)
  const { data: decisions } = useFetch<any>(`/api/positions/decisions/${symbol}?limit=15`, 60000)
  // Kanoniczny model decyzji — autorytatywne źródło dla rekomendacji i CTA
  const { data: decisionViewRaw, lastUpdated: dvUpdated } = useFetch<any>(`/api/signals/${symbol}/decision-view?mode=${mode}`, 15000)
  const decisionView = (decisionViewRaw as any)?.data ?? null
  const [orderStatus, setOrderStatus] = useState<string | null>(null)
  const [closeStatus, setCloseStatus] = useState<string | null>(null)
  const [buyAmt, setBuyAmt] = useState('50')
  const [showBuyForm, setShowBuyForm] = useState(false)
  const { data: forecast } = useFetch<any>(`/api/market/forecast/${symbol}`, 60000)
  const [panelGoal, setPanelGoal] = useState<UserGoal | null>(() => loadGoals()[symbol] || null)
  const [panelGoalInput, setPanelGoalInput] = useState('')
  const [panelGoalEdit, setPanelGoalEdit] = useState(false)
  const goalAnalysisUrl = `/api/positions/goal-analysis/${symbol}?mode=${mode}${panelGoal ? `&target_eur=${panelGoal.targetEur}` : ''}`
  const { data: goalAnalysis, loading: goalAnalysisLoading } = useFetch<any>(goalAnalysisUrl, 60000)

  const card = (analysis?.data || []).find((c: any) => c.symbol === symbol)
  const latestSignal = (signals?.data || []).find((s: any) => s.symbol === symbol)
  // Preferuj czas z decision-view (kanoniczny snapshot), fallback na analysis/signals
  const panelLastUpdated = dvUpdated ?? analysisUpdated ?? signalsUpdated

  const handleBuy = async () => {
    const amt = parseFloat(buyAmt.replace(',', '.'))
    if (!Number.isFinite(amt) || amt <= 0) { setOrderStatus('Podaj prawidłową kwotę'); return }
    if (currentPrice == null || currentPrice <= 0) { setOrderStatus('Brak aktualnej ceny — spróbuj ponownie za chwilę'); return }
    const quantity = parseFloat((amt / currentPrice).toFixed(8))
    if (quantity <= 0) { setOrderStatus('Obliczona ilość jest zbyt mała'); return }
    setOrderStatus('Wysyłam zlecenie...')
    try {
      const res = await fetch(`${getApiBase()}/api/orders?mode=${mode}`, {
        method: 'POST',
        headers: withAdminToken({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ symbol, side: 'BUY', order_type: 'MARKET', quantity }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setOrderStatus(`✓ Kupiono ${quantity.toFixed(6)} ${baseCoin} za ${amt} EUR`)
      setShowBuyForm(false)
    } catch (e: any) {
      setOrderStatus(`✗ ${e.message}`)
    }
  }

  const handleClose = async (fraction: number = 1) => {
    // LIVE spot: brak card.id, używamy symbolu do zamknięcia (sell market)
    if (mode === 'live' && card && !card.id && card.source === 'binance_spot') {
      const qty = fraction < 1 ? Number((card.quantity * fraction).toFixed(8)) : card.quantity
      if (!qty || qty <= 0) { setCloseStatus('Brak ilości do zamknięcia'); return }
      setCloseStatus(`Zamykam ${Math.round(fraction * 100)}%...`)
      try {
        const res = await fetch(`${getApiBase()}/api/orders?mode=${mode}`, {
          method: 'POST',
          headers: withAdminToken({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ symbol, side: 'SELL', order_type: 'MARKET', quantity: qty }),
        })
        const json = await res.json()
        if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
        setCloseStatus(`✓ Sprzedano ${qty.toFixed(6)} ${baseCoin}`)
      } catch (e: any) {
        setCloseStatus(`✗ ${e.message}`)
      }
      return
    }
    if (!card?.id) { setCloseStatus('Brak ID pozycji'); return }
    setCloseStatus(`Zamykam ${Math.round(fraction * 100)}%...`)
    try {
      const closeUrl = new URL(`${getApiBase()}/api/positions/${card.id}/close`)
      closeUrl.searchParams.set('mode', mode)
      if (fraction < 1 && card.quantity > 0) {
        closeUrl.searchParams.set('quantity', String(Number((card.quantity * fraction).toFixed(8))))
      }
      const res = await fetch(closeUrl.toString(), { method: 'POST', headers: withAdminToken() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setCloseStatus(`✓ Zamknięto ${Math.round(fraction * 100)}% pozycji`)
    } catch (e: any) {
      setCloseStatus(`✗ ${e.message}`)
    }
  }

  const displaySymbol = symbol.replace('EUR', '/EUR').replace('USDC', '/USDC').replace('USDT', '/USDT')
  const hasPosition = Boolean(card)
  const baseCoin = symbol.replace(/EUR$|USDT$|USDC$/, '')
  const currentPrice: number | null = ticker?.price ?? card?.current_price ?? (forecast as any)?.current_price ?? latestSignal?.price ?? null
  const panelLoading = analysisLoading && tickerLoading

  const formatPrice = (value: number | null | undefined, missing = '--') => {
    if (value == null || Number.isNaN(value)) return missing
    if (value < 0.0001) return value.toFixed(8)  // meme coiny: SHIB, PEPE
    if (value < 1) return value.toFixed(6)
    if (value < 100) return value.toFixed(4)
    return value.toFixed(2)
  }

  const formatFixed = (value: number | null | undefined, digits: number, missing = '--') => {
    if (value == null || Number.isNaN(value)) return missing
    return value.toFixed(digits)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end"
      style={{ background: 'rgba(0,0,0,0.6)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-xl bg-[#0a1420] border-l border-rldc-dark-border overflow-y-auto flex flex-col"
        style={{ boxShadow: '-8px 0 32px rgba(0,0,0,0.5)' }}
      >
        {/* Nagłówek */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-rldc-dark-border sticky top-0 bg-[#0a1420] z-10">
          <div className="flex items-center gap-3">
            <span className="text-xl font-bold text-slate-100">{displaySymbol}</span>
            {latestSignal && (
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                latestSignal.signal_type === 'BUY' ? 'bg-rldc-green-primary/20 text-rldc-green-primary' :
                latestSignal.signal_type === 'SELL' ? 'bg-rldc-red-primary/20 text-rldc-red-primary' :
                'bg-slate-500/20 text-slate-400'
              }`}>
                {latestSignal.signal_type === 'BUY' ? 'SYGNAŁ KUP' : latestSignal.signal_type === 'SELL' ? 'SYGNAŁ SPRZEDAJ' : 'OBSERWUJ'}
              </span>
            )}
            {card && (
              <span className="px-2 py-0.5 rounded text-[10px] bg-rldc-teal-primary/20 text-rldc-teal-primary border border-rldc-teal-primary/20">
                W PORTFELU
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <DataStatus lastUpdated={panelLastUpdated} loading={panelLoading} error={null} refreshMs={15000} />
            <button onClick={onClose} className="text-slate-400 hover:text-slate-100 transition text-lg px-2">✕</button>
          </div>
        </div>

        <div className="flex-1 p-5 space-y-5">
          {/* ━━━ GŁÓWNA REKOMENDACJA ━━━ */}
          {(card || latestSignal || forecast || decisionView) && (() => {
            const rec = buildMainRecommendation(card, latestSignal, forecast, hasPosition, decisionView)
            // primary_cta z backendu jest autorytatywne; fallback do reguły lokalnej
            const backendCta = decisionView?.primary_cta as string | null | undefined
            const isBuyRec = backendCta
              ? backendCta === 'BUY'
              : (rec.decision === 'KUP TERAZ' || rec.decision === 'KANDYDAT DO WEJŚCIA')
            const isSellAll = backendCta
              ? (backendCta === 'SELL' && hasPosition)
              : rec.decision === 'ZAMKNIJ POZYCJĘ'
            const isSellPart = !backendCta && rec.decision === 'SPRZEDAJ CZĘŚĆ'
            return (
              <div className={`rounded-xl border-2 px-5 py-4 ${rec.bg}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">Rekomendacja dla {displaySymbol}</div>
                  {rec.urgency === 'high' && <span className="text-[9px] px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 font-bold uppercase tracking-wider">pilne</span>}
                  {rec.urgency === 'medium' && <span className="text-[9px] px-2 py-0.5 rounded-full bg-yellow-400/20 text-yellow-400 font-bold uppercase tracking-wider">uwaga</span>}
                </div>
                <div className={`text-3xl font-black tracking-wide mb-3 ${rec.color}`}>{rec.decision}</div>
                <div className="space-y-1.5 mb-3">
                  {rec.reasons.map((r, i) => (
                    <div key={i} className="text-xs text-slate-400 flex items-start gap-1.5">
                      <span className={`mt-0.5 shrink-0 ${rec.color}`}>•</span>
                      <span>{r}</span>
                    </div>
                  ))}
                </div>
                {(isBuyRec || isSellPart || isSellAll) && (
                  <div className="flex flex-wrap gap-2">
                    {isBuyRec && (
                      <button
                        onClick={() => setShowBuyForm(true)}
                        className="px-4 py-2 rounded-lg text-sm font-bold bg-rldc-green-primary/20 text-rldc-green-primary border border-rldc-green-primary/40 hover:bg-rldc-green-primary/35 transition"
                      >
                        ▲ Kup {displaySymbol}
                      </button>
                    )}
                    {isSellPart && hasPosition && card?.id && (
                      <button
                        onClick={() => handleClose(0.5)}
                        className="px-4 py-2 rounded-lg text-sm font-bold bg-orange-400/15 text-orange-400 border border-orange-400/30 hover:bg-orange-400/25 transition"
                      >
                        ▼ Sprzedaj 50%
                      </button>
                    )}
                    {isSellAll && hasPosition && card?.id && (
                      <>
                        <button
                          onClick={() => handleClose(0.5)}
                          className="px-4 py-2 rounded-lg text-sm font-bold bg-rldc-red-primary/15 text-rldc-red-primary border border-rldc-red-primary/30 hover:bg-rldc-red-primary/25 transition"
                        >
                          ▼ Sprzedaj 50%
                        </button>
                        <button
                          onClick={() => handleClose(1)}
                          className="px-4 py-2 rounded-lg text-sm font-bold bg-rldc-red-primary/20 text-rldc-red-primary border border-rldc-red-primary/40 hover:bg-rldc-red-primary/30 transition"
                        >
                          ▼ Zamknij całość
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })()}

          {/* ━━━ STAN TERAZ ━━━ (jeden skonsolidowany blok) */}
          <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">Stan teraz</div>

            {/* Wiersz 1: cena + wpis (jeśli pozycja) */}
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <div className="text-[10px] text-slate-500 mb-0.5">Cena teraz</div>
                <div className="text-xl font-mono font-bold text-slate-100">
                  {currentPrice != null
                    ? formatPrice(currentPrice)
                    : '--'} <span className="text-sm font-normal text-slate-500">EUR</span>
                </div>
              </div>
              {card ? (
                <div>
                  <div className="text-[10px] text-slate-500 mb-0.5">Kupiono po</div>
                  <div className="text-xl font-mono font-bold text-slate-300">
                    {formatPrice(card.entry_price, 'brak danych')} <span className="text-sm font-normal text-slate-500">EUR</span>
                  </div>
                </div>
              ) : latestSignal ? (
                <div>
                  <div className="text-[10px] text-slate-500 mb-0.5">Pewność sygnału</div>
                  <div className="text-xl font-mono font-bold text-slate-100">
                    {Math.round((latestSignal.confidence || 0) * 100)}<span className="text-sm font-normal text-slate-500">%</span>
                  </div>
                </div>
              ) : null}
            </div>

            {/* Wiersz 2: wynik + wartość + ilość (tylko przy pozycji) */}
            {card && (
              <div className="grid grid-cols-3 gap-3 mb-3">
                <div>
                  <div className="text-[10px] text-slate-500 mb-0.5">Wynik</div>
                  <div className={`text-base font-mono font-bold ${pnlColor(card.pnl_eur || 0)}`}>
                    {(card.pnl_eur >= 0 ? '+' : '')}{formatFixed(card.pnl_eur, 2, '0.00')} EUR
                  </div>
                  <div className={`text-[10px] ${pnlColor(card.pnl_pct || 0)}`}>
                    {(card.pnl_pct >= 0 ? '+' : '')}{formatFixed(card.pnl_pct, 2, '0.00')}%
                  </div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500 mb-0.5">Wartość pozycji</div>
                  <div className="text-base font-mono font-bold text-slate-200">
                    {formatFixed(card.position_value_eur, 2, 'brak danych')} EUR
                  </div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500 mb-0.5">Ilość</div>
                  <div className="text-base font-mono font-bold text-slate-200">
                    {formatPrice(card.quantity, 'brak danych')} {baseCoin}
                  </div>
                </div>
              </div>
            )}

            {/* Wiersz 3: analiza techniczna + TP/SL */}
            {card && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-2 border-t border-rldc-dark-border/60">
              <div>
                <div className="text-[10px] text-slate-500">Trend</div>
                <div className={`text-sm font-semibold mt-0.5 ${card.trend === 'WZROSTOWY' ? 'text-rldc-green-primary' : card.trend === 'SPADKOWY' ? 'text-rldc-red-primary' : 'text-slate-400'}`}>
                  {card.trend === 'WZROSTOWY' ? '▲ Wzrost' : card.trend === 'SPADKOWY' ? '▼ Spadek' : '— Boczny'}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-slate-500">RSI</div>
                <div className={`text-sm font-mono font-bold mt-0.5 ${card.rsi != null ? (card.rsi < 30 ? 'text-rldc-green-primary' : card.rsi > 70 ? 'text-rldc-red-primary' : 'text-slate-200') : 'text-slate-500'}`}>
                  {card.rsi ?? '--'}
                </div>
              </div>
              {card.planned_tp != null && (
                <div>
                  <div className="text-[10px] text-slate-500">Cel zysku</div>
                  <div className="text-sm font-mono text-rldc-green-primary mt-0.5">
                    {card.planned_tp < 1 ? card.planned_tp.toFixed(6) : card.planned_tp.toFixed(4)}
                  </div>
                  {currentPrice != null && (
                    <div className="text-[10px] text-rldc-green-primary/70">
                      +{(((card.planned_tp - currentPrice) / currentPrice) * 100).toFixed(1)}%
                    </div>
                  )}
                </div>
              )}
              {card.planned_sl != null && (
                <div>
                  <div className="text-[10px] text-slate-500">Stop straty</div>
                  <div className="text-sm font-mono text-rldc-red-primary mt-0.5">
                    {card.planned_sl < 1 ? card.planned_sl.toFixed(6) : card.planned_sl.toFixed(4)}
                  </div>
                  {currentPrice != null && (
                    <div className="text-[10px] text-rldc-red-primary/70">
                      {(((card.planned_sl - currentPrice) / currentPrice) * 100).toFixed(1)}%
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          </div>
          {/* koniec bloku Stan teraz */}

          {/* Wykres historyczny + prognoza */}
          <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs font-semibold text-slate-300">Wykres + prognoza AI</div>
              <div className="flex items-center gap-4 text-[10px]">
                <span className="flex items-center gap-1"><span className="inline-block w-4 h-0.5 bg-rldc-teal-primary"></span> Historia</span>
                <span className="flex items-center gap-1"><span className="inline-block w-4 h-0.5 bg-rldc-orange-primary" style={{backgroundImage:'repeating-linear-gradient(90deg,#f97316 0,#f97316 4px,transparent 4px,transparent 8px)'}}></span> Prognoza</span>
              </div>
            </div>
            <ForecastChart symbol={symbol} />
          </div>

          {/* Prognoza AI — horyzonty 1h / 4h / 24h */}
          {forecast && (
            <div>
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Prognoza AI — horyzonty czasowe</div>
              <div className="grid grid-cols-3 gap-2">
                {(['forecast_1h', 'forecast_4h', 'forecast_24h'] as const).map((key, i) => {
                  const f = (forecast as Record<string, any>)[key]
                  const label = ['1 godzina', '4 godziny', '24 godziny'][i]
                  if (!f) return null
                  const dirColor = f.direction === 'WZROSTOWY' ? 'text-rldc-green-primary' : f.direction === 'SPADKOWY' ? 'text-rldc-red-primary' : 'text-slate-400'
                  return (
                    <div key={key} className="terminal-card border border-rldc-dark-border rounded-lg px-3 py-2">
                      <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1">{label}</div>
                      <div className={`text-sm font-bold ${dirColor}`}>{f.direction ?? '--'}</div>
                      <div className="text-xs font-mono text-slate-300">{f.projected_pct != null ? `${f.projected_pct > 0 ? '+' : ''}${f.projected_pct.toFixed(2)}%` : '--'}</div>
                      <div className="text-[9px] text-slate-500 mt-0.5">Jakość: {f.model_quality ?? '--'}%</div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Analiza i Ocena Twojego Celu */}
          {(() => {
            const ga = goalAnalysis as any
            const realityColor = (score: number) =>
              score >= 80 ? 'text-rldc-green-primary' :
              score >= 60 ? 'text-emerald-400' :
              score >= 40 ? 'text-yellow-400' :
              score >= 20 ? 'text-orange-400' : 'text-rldc-red-primary'
            const decisionGoalColor = (d: string) =>
              d === 'sprzedaj_teraz' ? 'text-rldc-green-primary' :
              d === 'zmień_cel' ? 'text-yellow-400' :
              d === 'rozważ_zamknięcie' ? 'text-rldc-red-primary' :
              d === 'czekaj_na_odbicie' ? 'text-blue-400' : 'text-rldc-teal-primary'
            return (
              <div className="bg-[#0b121a] rounded-lg border border-rldc-dark-border/50 px-4 py-3 space-y-3">
                {/* Nagłówek z przyciskiem */}
                <div className="flex items-center justify-between">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">Ocena Twojego Celu</div>
                  <div className="flex items-center gap-2">
                    {!panelGoal && (forecast as any)?.forecast_24h && (() => {
                      const f24 = (forecast as any).forecast_24h
                      const current = card?.position_value_eur ?? 0
                      return current > 0 ? (
                        <button
                          onClick={() => {
                            const pct = f24.projected_pct ?? 0
                            const suggested = current * (1 + Math.max(pct, 2) / 100)
                            setPanelGoalInput(suggested.toFixed(2))
                            setPanelGoalEdit(true)
                          }}
                          className="text-[10px] text-slate-500 hover:text-rldc-teal-primary transition"
                          title="Sugestia na podstawie prognozy AI 24h"
                        >✦ AI sugestia</button>
                      ) : null
                    })()}
                    <button
                      onClick={() => { setPanelGoalEdit(!panelGoalEdit); setPanelGoalInput(panelGoal ? String(panelGoal.targetEur) : '') }}
                      className="text-[10px] text-rldc-teal-primary hover:underline"
                    >
                      {panelGoal ? 'Zmień cel' : 'Ustaw cel'}
                    </button>
                  </div>
                </div>

                {/* Kontekst AI sugestii przy edycji */}
                {panelGoalEdit && (forecast as any)?.forecast_24h && (() => {
                  const f24 = (forecast as any).forecast_24h
                  return (
                    <div className="px-2 py-1.5 rounded bg-rldc-teal-primary/5 border border-rldc-teal-primary/15 text-[10px] text-slate-500 space-y-0.5">
                      <div className="text-rldc-teal-primary/80 font-semibold">Podstawa sugestii AI:</div>
                      <div>Prognoza 24h: <span className={f24.direction === 'WZROSTOWY' ? 'text-rldc-green-primary' : f24.direction === 'SPADKOWY' ? 'text-rldc-red-primary' : 'text-slate-400'}>{f24.direction} ({f24.projected_pct != null ? (f24.projected_pct > 0 ? '+' : '') + f24.projected_pct.toFixed(2) + '%' : '--'})</span></div>
                      <div>Jakość modelu: <span className={f24.model_quality >= 60 ? 'text-rldc-green-primary' : f24.model_quality >= 40 ? 'text-yellow-400' : 'text-rldc-red-primary'}>{f24.model_quality ?? '--'}%</span></div>
                    </div>
                  )
                })()}

                {/* Formularz celu */}
                {panelGoalEdit && (
                  <div className="flex items-center gap-2">
                    <input
                      type="number" min="0" step="1"
                      value={panelGoalInput}
                      onChange={(e) => setPanelGoalInput(e.target.value)}
                      className="w-28 px-2 py-1 text-xs rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 font-mono"
                      placeholder="np. 200"
                    />
                    <span className="text-xs text-slate-400">EUR</span>
                    <button
                      onClick={() => {
                        const t = parseFloat(panelGoalInput.replace(',', '.'))
                        if (!isFinite(t) || t <= 0) return
                        const g: UserGoal = { targetEur: t, setAt: new Date().toISOString() }
                        saveGoal(symbol, g)
                        setPanelGoal(g)
                        setPanelGoalEdit(false)
                      }}
                      className="px-2 py-1 text-xs rounded bg-rldc-teal-primary/20 text-rldc-teal-primary border border-rldc-teal-primary/30 hover:bg-rldc-teal-primary/35 transition"
                    >Zapisz</button>
                    {panelGoal && (
                      <button
                        onClick={() => { removeGoal(symbol); setPanelGoal(null); setPanelGoalEdit(false) }}
                        className="px-2 py-1 text-xs rounded text-slate-500 border border-rldc-dark-border hover:bg-slate-500/10 transition"
                      >Usuń</button>
                    )}
                  </div>
                )}

                {/* Brak celu */}
                {!panelGoal && !panelGoalEdit && (
                  <div className="text-xs text-slate-600">Nie ustawiono celu. Kliknij „Ustaw cel" aby uruchomić silnik oceny.</div>
                )}

                {/* Ładowanie analizy */}
                {goalAnalysisLoading && panelGoal && (
                  <div className="text-[10px] text-slate-600 animate-pulse">Analizuję cel...</div>
                )}

                {/* Wyniki analizy backendowej */}
                {ga && !goalAnalysisLoading && ga.goal_decision != null && (
                  <div className="space-y-3">
                    {/* Cel + score */}
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="text-xs text-slate-500">Cel: </span>
                        <span className="text-sm font-mono font-bold text-slate-200">{ga.goal_value != null ? ga.goal_value.toFixed(2) : '--'} EUR</span>
                        {ga.goal_source === 'auto_10pct' && (
                          <span className="ml-1 text-[9px] text-slate-600">(auto +10%)</span>
                        )}
                      </div>
                      <div className="text-right">
                        <span className={`text-sm font-bold ${realityColor(ga.goal_reality_score ?? 50)}`}>
                          {ga.goal_reality_label_pl ?? '--'}
                        </span>
                        <span className="text-[10px] text-slate-600 ml-1">({ga.goal_reality_score ?? '--'}/100)</span>
                      </div>
                    </div>

                    {/* Pasek realności */}
                    <div className="h-1.5 bg-rldc-dark-bg rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          (ga.goal_reality_score ?? 0) >= 80 ? 'bg-rldc-green-primary' :
                          (ga.goal_reality_score ?? 0) >= 60 ? 'bg-emerald-400' :
                          (ga.goal_reality_score ?? 0) >= 40 ? 'bg-yellow-400' :
                          (ga.goal_reality_score ?? 0) >= 20 ? 'bg-orange-400' : 'bg-rldc-red-primary'
                        }`}
                        style={{ width: `${ga.goal_reality_score ?? 0}%` }}
                      />
                    </div>

                    {/* ETA + ruch */}
                    <div className="grid grid-cols-3 gap-2">
                      <div className="terminal-card border border-rldc-dark-border rounded px-2 py-1.5">
                        <div className="text-[9px] text-slate-600 uppercase tracking-widest">Do celu</div>
                        <div className={`text-sm font-bold font-mono ${pnlColor(ga.needed_move_eur ?? 0)}`}>
                          {ga.needed_move_eur != null ? (ga.needed_move_eur > 0 ? '+' : '') + ga.needed_move_eur.toFixed(2) : '--'} EUR
                        </div>
                      </div>
                      <div className="terminal-card border border-rldc-dark-border rounded px-2 py-1.5">
                        <div className="text-[9px] text-slate-600 uppercase tracking-widest">Ruch %</div>
                        <div className={`text-sm font-bold font-mono ${pnlColor(ga.needed_move_pct ?? 0)}`}>
                          {ga.needed_move_pct != null ? (ga.needed_move_pct > 0 ? '+' : '') + ga.needed_move_pct.toFixed(2) + '%' : '--'}
                        </div>
                      </div>
                      <div className="terminal-card border border-rldc-dark-border rounded px-2 py-1.5">
                        <div className="text-[9px] text-slate-600 uppercase tracking-widest">ETA</div>
                        <div className="text-xs font-bold text-slate-300">{ga.eta_label ?? '--'}</div>
                      </div>
                    </div>

                    {/* Blokery */}
                    {(ga.main_blockers as string[] | undefined)?.length ? (
                      <div>
                        <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1">Blokery</div>
                        <div className="space-y-0.5">
                          {(ga.main_blockers as string[]).map((b: string, i: number) => (
                            <div key={i} className="flex items-start gap-1.5 text-[10px] text-slate-400">
                              <span className={b.startsWith('Brak') ? 'text-rldc-green-primary' : 'text-orange-400'}>
                                {b.startsWith('Brak') ? '✓' : '⚠'}
                              </span>
                              <span>{b}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    {/* Warunki wymagane */}
                    {(ga.required_conditions as string[] | undefined)?.length ? (
                      <div>
                        <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1">Wymagane warunki</div>
                        <div className="space-y-0.5">
                          {(ga.required_conditions as string[]).slice(0, 3).map((c: string, i: number) => (
                            <div key={i} className="flex items-start gap-1.5 text-[10px] text-slate-500">
                              <span className="text-rldc-teal-primary">→</span>
                              <span>{c}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    {/* Alternatywne cele AI */}
                    {(ga.suggested_safe_target || ga.suggested_ai_exit) && (
                      <div>
                        <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1.5">Alternatywne cele AI</div>
                        <div className="grid grid-cols-2 gap-1.5">
                          {[
                            { key: 'suggested_safe_target', label: 'Bezpieczny' },
                            { key: 'suggested_balanced_target', label: 'Wyważony' },
                            { key: 'suggested_aggressive_target', label: 'Agresywny' },
                            { key: 'suggested_ai_exit', label: 'Wyjście AI' },
                          ].map(({ key, label }) => {
                            const alt = (ga as any)[key]
                            if (!alt) return null
                            return (
                              <div
                                key={key}
                                className="terminal-card border border-rldc-dark-border rounded px-2 py-1.5 cursor-pointer hover:border-rldc-teal-primary/40 transition"
                                title={alt.reason}
                                onClick={() => { setPanelGoalInput(String(alt.value)) }}
                              >
                                <div className="text-[9px] text-slate-600 mb-0.5">{label}</div>
                                <div className="text-xs font-mono font-bold text-slate-300">{alt.value != null ? alt.value.toFixed(2) : '--'} EUR</div>
                                <div className={`text-[9px] ${realityColor(alt.reality_score)}`}>{alt.reality_score}/100</div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {/* Decyzja AI */}
                    {ga.goal_decision && (
                      <div className={`rounded border px-3 py-2 ${
                        ga.goal_decision === 'sprzedaj_teraz' ? 'border-rldc-green-primary/30 bg-rldc-green-primary/5' :
                        ga.goal_decision === 'zmień_cel' ? 'border-yellow-400/30 bg-yellow-400/5' :
                        ga.goal_decision === 'rozważ_zamknięcie' ? 'border-rldc-red-primary/30 bg-rldc-red-primary/5' :
                        'border-rldc-teal-primary/20 bg-rldc-teal-primary/5'
                      }`}>
                        <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1">Co teraz zrobić?</div>
                        <div className={`text-xs font-bold mb-1 ${decisionGoalColor(ga.goal_decision)}`}>
                          {ga.goal_decision === 'sprzedaj_teraz' ? '✓ SPRZEDAJ TERAZ' :
                           ga.goal_decision === 'zmień_cel' ? '↕ ZMIEŃ CEL' :
                           ga.goal_decision === 'rozważ_zamknięcie' ? '⚠ ROZWAŻ ZAMKNIĘCIE' :
                           ga.goal_decision === 'czekaj_na_odbicie' ? '⟳ CZEKAJ NA ODBICIE' :
                           '→ CZEKAJ'}
                        </div>
                        <div className="text-[10px] text-slate-400 leading-relaxed">{ga.goal_decision_reason_pl}</div>
                      </div>
                    )}
                  </div>
                )}

                {/* Brak danych technicznych */}
                {!ga && !goalAnalysisLoading && panelGoal && (
                  <div className="text-[10px] text-slate-600">
                    Brak danych technicznych dla {symbol}. Poczekaj na synchronizację danych rynkowych.
                  </div>
                )}
              </div>
            )
          })()}

          {/* Decyzja systemu */}
          {card && (
            <div className={`rounded-lg border px-4 py-3 ${decisionBg(card.decision)}`}>
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Decyzja systemu</div>
              <div className={`text-lg font-bold ${decisionColor(card.decision)}`}>{card.decision}</div>
              <div className="mt-2 space-y-1">
                {(card.reasons || []).slice(0, 3).map((r: string, i: number) => (
                  <div key={i} className="text-xs text-slate-400 flex items-start gap-1.5">
                    <span className="text-rldc-teal-primary mt-0.5">•</span>
                    <span>{r}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Poprzednie prognozy — jak trafne? */}
          {accuracy && (
            <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border p-4">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">Poprzednie prognozy — jak trafne?</div>
              {/* Trafność per horyzont: 1h / 4h / 24h */}
              {(() => {
                const horizons = ['1h', '4h', '24h']
                const bh = horizons.map(h => {
                  const recs = (accuracy.records || []).filter((r: any) => (r.horizon || '').toString() === h)
                  const total = recs.length
                  const correct = recs.filter((r: any) => r.correct_direction === true).length
                  return { h, total, pct: total > 0 ? Math.round(correct / total * 100) : null }
                })
                return (
                  <div className="grid grid-cols-3 gap-2 mb-3">
                    {bh.map(({ h, total, pct }) => (
                      <div key={h} className="terminal-card border border-rldc-dark-border rounded-lg px-3 py-2 text-center">
                        <div className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">{h}</div>
                        <div className={`text-base font-bold ${
                          pct == null ? 'text-slate-600' :
                          pct >= 60 ? 'text-rldc-green-primary' :
                          pct >= 45 ? 'text-yellow-400' : 'text-rldc-red-primary'
                        }`}>{pct != null ? `${pct}%` : '--'}</div>
                        <div className="text-[9px] text-slate-600">{total > 0 ? `${total} prognoz` : 'brak danych'}</div>
                      </div>
                    ))}
                  </div>
                )
              })()}
              {/* Ogólne statystyki */}
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="terminal-card border border-rldc-dark-border rounded-lg px-3 py-2">
                  <div className="text-[10px] text-slate-500">Trafność kierunku</div>
                  <div className={`text-lg font-bold mt-0.5 ${
                    accuracy.direction_accuracy_pct == null ? 'text-slate-500' :
                    accuracy.direction_accuracy_pct >= 60 ? 'text-rldc-green-primary' :
                    accuracy.direction_accuracy_pct >= 45 ? 'text-yellow-400' : 'text-rldc-red-primary'
                  }`}>
                    {accuracy.direction_accuracy_pct != null ? `${accuracy.direction_accuracy_pct}%` : '--'}
                  </div>
                  <div className="text-[10px] text-slate-600">ze wszystkich prognoz</div>
                </div>
                <div className="terminal-card border border-rldc-dark-border rounded-lg px-3 py-2">
                  <div className="text-[10px] text-slate-500">Błąd średni</div>
                  <div className={`text-lg font-bold mt-0.5 ${
                    accuracy.avg_error_pct == null ? 'text-slate-500' :
                    accuracy.avg_error_pct <= 2 ? 'text-rldc-green-primary' :
                    accuracy.avg_error_pct <= 5 ? 'text-yellow-400' : 'text-rldc-red-primary'
                  }`}>
                    {accuracy.avg_error_pct != null ? `${accuracy.avg_error_pct}%` : '--'}
                  </div>
                  <div className="text-[10px] text-slate-600">odchylenie ceny</div>
                </div>
              </div>
              {accuracy.records?.slice(0, 5).map((r: any, i: number) => (
                <div key={i} className="flex items-center justify-between text-[11px] py-0.5 border-t border-rldc-dark-border/50">
                  <span className="text-slate-500">{r.horizon} · {r.forecast_ts ? new Date(r.forecast_ts).toLocaleDateString('pl-PL') : ''}</span>
                  <span className={`font-mono ${r.correct_direction === true ? 'text-rldc-green-primary' : r.correct_direction === false ? 'text-rldc-red-primary' : 'text-slate-500'}`}>
                    {r.direction} {r.correct_direction === true ? '✓' : r.correct_direction === false ? '✗' : ''}
                  </span>
                  <span className="font-mono text-slate-400">{r.error_pct != null ? `±${r.error_pct}%` : '--'}</span>
                </div>
              ))}
              {accuracy.count === 0 && (
                <div className="text-xs text-slate-500 space-y-1">
                  <div>Brak jeszcze sprawdzonych prognoz dla {symbol.replace(/EUR$|USDT$|USDC$/, '')}.</div>
                  <div className="text-slate-600">System porównuje prognozy z rzeczywistymi cenami po upływie horyzontu (1h / 4h / 24h). Dane pojawią się automatycznie po pierwszym cyklu.</div>
                  {(forecast as any)?.forecast_1h && (
                    <div className="mt-1 text-rldc-teal-primary/60">Bieżąca prognoza 1h: {(forecast as any).forecast_1h.direction} ({(forecast as any).forecast_1h.projected_pct != null ? ((forecast as any).forecast_1h.projected_pct > 0 ? '+' : '') + (forecast as any).forecast_1h.projected_pct.toFixed(2) + '%' : '--'})</div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Co bot robił z tym symbolem */}
          {decisions && decisions.count > 0 && (
            <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border p-4">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Co bot robił z tym symbolem</div>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {decisions.data.map((d: any, i: number) => (
                  <div key={i} className="flex items-start gap-2 text-[10px] py-1 border-b border-rldc-dark-border/40">
                    <span className="text-slate-600 shrink-0">{d.timestamp ? d.timestamp.slice(0, 16).replace('T', ' ') : ''}</span>
                    <span className={`shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold ${
                      d.action_type?.includes('allow') || d.action_type?.includes('BUY') ? 'bg-rldc-green-primary/15 text-rldc-green-primary' :
                      d.action_type?.includes('block') || d.action_type?.includes('kill') ? 'bg-rldc-red-primary/15 text-rldc-red-primary' :
                      'bg-slate-500/15 text-slate-400'
                    }`}>{d.action_type || '?'}</span>
                    <span className="text-slate-500 leading-tight">{d.reason_code}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Co teraz zrobić? — podsumowanie decyzji */}
          {(() => {
            let decision = ''
            let decColor = 'text-slate-400'
            let decBg = 'bg-slate-500/10 border-slate-500/20'
            let summary = 'Brak danych — obserwuj rynek i zaczekaj na sygnał.'
            if (card?.decision) {
              const d = (card.decision as string).toUpperCase()
              if (d.includes('KUP') || d === 'BUY') {
                decision = 'KUP'; decColor = 'text-rldc-green-primary'; decBg = 'bg-rldc-green-primary/10 border-rldc-green-primary/30'
                summary = 'System rekomenduje zakup. Warunki techniczne sprzyjają wejściu na pozycję.'
              } else if (d.includes('SPRZEDAJ') || d === 'SELL' || d.includes('ZAMKNIJ')) {
                decision = 'SPRZEDAJ / ZAMKNIJ'; decColor = 'text-rldc-red-primary'; decBg = 'bg-rldc-red-primary/10 border-rldc-red-primary/30'
                summary = 'System rekomenduje zamknięcie pozycji. Warunki wskazują na ryzyko dalszego spadku.'
              } else if (d.includes('TRZYMAJ') || d === 'HOLD') {
                decision = 'TRZYMAJ'; decColor = 'text-rldc-teal-primary'; decBg = 'bg-rldc-teal-primary/10 border-rldc-teal-primary/30'
                summary = 'System zaleca utrzymanie pozycji. Warunki techniczne są korzystne lub neutralne.'
              } else {
                decision = card.decision; summary = 'Obserwuj rynek i czekaj na wyraźniejszy sygnał.'
              }
            } else if (latestSignal?.signal_type === 'BUY') {
              decision = 'KANDYDAT DO WEJŚCIA'; decColor = 'text-rldc-green-primary'; decBg = 'bg-rldc-green-primary/10 border-rldc-green-primary/30'
              summary = `Sygnał kupna z pewnością ${Math.round((latestSignal.confidence || 0) * 100)}%. Nie masz jeszcze pozycji na tym instrumencie.`
            } else if (latestSignal?.signal_type === 'SELL') {
              decision = 'NIE WCHODŹ'; decColor = 'text-rldc-red-primary'; decBg = 'bg-rldc-red-primary/10 border-rldc-red-primary/30'
              summary = 'Sygnał sprzedaży — rynek może dalej spadać. Nie otwieraj pozycji.'
            } else {
              decision = 'OBSERWUJ'
            }
            if (!decision) return null
            const isBuy = decision === 'KUP' || decision === 'KANDYDAT DO WEJŚCIA'
            const isSell = decision === 'SPRZEDAJ / ZAMKNIJ'
            const isHold = decision === 'TRZYMAJ'
            return (
              <div className={`rounded-lg border px-4 py-3 ${decBg}`}>
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Co teraz zrobić?</div>
                <div className={`text-2xl font-bold tracking-wide mb-1.5 ${decColor}`}>{decision}</div>
                <div className="text-sm text-slate-400 leading-snug">{summary}</div>
                {(forecast as any)?.forecast_1h && (
                  <div className="mt-1.5 text-xs text-slate-500">
                    {'Prognoza 1h: '}
                    <span className={(forecast as any).forecast_1h.direction === 'WZROSTOWY' ? 'text-rldc-green-primary' : (forecast as any).forecast_1h.direction === 'SPADKOWY' ? 'text-rldc-red-primary' : 'text-slate-400'}>
                      {(forecast as any).forecast_1h.direction === 'WZROSTOWY' ? '▲' : (forecast as any).forecast_1h.direction === 'SPADKOWY' ? '▼' : '—'}{' '}
                      {(forecast as any).forecast_1h.direction}
                      {(forecast as any).forecast_1h.projected_pct != null ? ` (${(forecast as any).forecast_1h.projected_pct > 0 ? '+' : ''}${((forecast as any).forecast_1h.projected_pct as number).toFixed(2)}%)` : ''}
                    </span>
                  </div>
                )}
                {(isBuy || isSell || isHold) && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {isBuy && (
                      <button
                        onClick={() => setShowBuyForm(true)}
                        className="px-3 py-1.5 rounded text-xs font-bold bg-rldc-green-primary/20 text-rldc-green-primary border border-rldc-green-primary/40 hover:bg-rldc-green-primary/35 transition"
                      >
                        ▲ Otwórz formularz kupna
                      </button>
                    )}
                    {(isSell || isHold) && hasPosition && card?.id && (
                      <>
                        <button
                          onClick={() => handleClose(0.5)}
                          className="px-3 py-1.5 rounded text-xs font-bold bg-rldc-red-primary/15 text-rldc-red-primary border border-rldc-red-primary/30 hover:bg-rldc-red-primary/25 transition"
                        >
                          ▼ Sprzedaj 50%
                        </button>
                        {isSell && (
                          <button
                            onClick={() => handleClose(1)}
                            className="px-3 py-1.5 rounded text-xs font-bold bg-rldc-red-primary/20 text-rldc-red-primary border border-rldc-red-primary/40 hover:bg-rldc-red-primary/30 transition"
                          >
                            ▼ Sprzedaj 100%
                          </button>
                        )}
                      </>
                    )}
                    {isHold && (
                      <span className="px-3 py-1.5 rounded text-xs text-slate-500 border border-rldc-dark-border bg-slate-500/5">
                        Trzymaj i obserwuj
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })()}

          {/* Przyciski akcji */}
          <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border p-4">
            <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">Akcje</div>

            {/* KUP */}
            {true && (
              <div className="mb-3">
                {!showBuyForm ? (
                  <button
                    onClick={() => setShowBuyForm(true)}
                    className="w-full px-4 py-2.5 rounded-lg text-sm font-bold bg-rldc-green-primary/15 text-rldc-green-primary border border-rldc-green-primary/30 hover:bg-rldc-green-primary/25 transition"
                  >
                    ▲ KUP {displaySymbol}
                  </button>
                ) : (
                  <div className="space-y-2">
                    <div className="flex gap-1.5">
                      {[25, 50, 100, 200].map((preset) => (
                        <button
                          key={preset}
                          onClick={() => setBuyAmt(String(preset))}
                          className={`flex-1 py-1 rounded text-xs font-mono border transition ${
                            buyAmt === String(preset)
                              ? 'bg-rldc-green-primary/25 text-rldc-green-primary border-rldc-green-primary/40'
                              : 'bg-rldc-dark-bg text-slate-400 border-rldc-dark-border hover:border-slate-500'
                          }`}
                        >
                          {preset}
                        </button>
                      ))}
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={buyAmt}
                        onChange={(e) => setBuyAmt(e.target.value)}
                        className="flex-1 px-3 py-1.5 text-sm rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 font-mono"
                        placeholder="50"
                      />
                      <span className="text-sm text-slate-400">EUR</span>
                    </div>
                    {currentPrice != null && parseFloat(buyAmt) > 0 && (
                      <div className="text-[10px] text-slate-500">
                        ≈ {(parseFloat(buyAmt) / currentPrice).toFixed(6)} {baseCoin} · cena {currentPrice < 1 ? currentPrice.toFixed(6) : currentPrice.toFixed(2)} EUR
                      </div>
                    )}
                    <div className="flex gap-2">
                      <button
                        onClick={handleBuy}
                        className="flex-1 px-4 py-2 rounded text-sm font-bold bg-rldc-green-primary/20 text-rldc-green-primary border border-rldc-green-primary/30 hover:bg-rldc-green-primary/35 transition"
                      >
                        Potwierdź kupno
                      </button>
                      <button
                        onClick={() => { setShowBuyForm(false); setOrderStatus(null) }}
                        className="px-3 py-2 rounded text-sm text-slate-400 border border-rldc-dark-border hover:bg-slate-500/10 transition"
                      >
                        Anuluj
                      </button>
                    </div>
                  </div>
                )}
                {orderStatus && (
                  <div className={`mt-2 text-xs ${orderStatus.startsWith('✓') ? 'text-rldc-green-primary' : orderStatus.startsWith('✗') ? 'text-rldc-red-primary' : 'text-slate-400'}`}>
                    {orderStatus}
                  </div>
                )}
              </div>
            )}

            {/* ZAMKNIJ pozycję jeśli otwarta */}
            {hasPosition && card?.id && (
              <div>
                <div className="text-[10px] text-slate-500 mb-1.5">Zamknij pozycję (sprzedaj):</div>
                <div className="grid grid-cols-3 gap-2">
                  {[0.25, 0.5, 1].map((fraction) => (
                    <button
                      key={fraction}
                      onClick={() => handleClose(fraction)}
                      className="py-2 rounded text-sm font-bold bg-rldc-red-primary/15 text-rldc-red-primary border border-rldc-red-primary/30 hover:bg-rldc-red-primary/25 transition"
                    >
                      ▼ {Math.round(fraction * 100)}%
                    </button>
                  ))}
                </div>
                {closeStatus && (
                  <div className={`mt-2 text-xs ${closeStatus.startsWith('✓') ? 'text-rldc-green-primary' : closeStatus.startsWith('✗') ? 'text-rldc-red-primary' : 'text-slate-400'}`}>
                    {closeStatus}
                  </div>
                )}
              </div>
            )}


          </div>
        </div>
      </div>
    </div>
  )
}

export default function MainContent({ activeView, tradingMode }: MainContentProps) {
  const mode = tradingMode === 'live' ? 'live' : 'demo'
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)

  return (
    <>
      {activeView === 'dashboard' && (
        <CommandCenterView mode={mode} onSymbolClick={setSelectedSymbol} />
      )}
      {activeView === 'dashboard-classic' && (
        <DashboardV2View tradingMode={tradingMode} onSymbolClick={setSelectedSymbol} />
      )}
      {activeView !== 'dashboard' && activeView !== 'dashboard-classic' && (
        <OtherView activeView={activeView} tradingMode={tradingMode} onSymbolClick={setSelectedSymbol} />
      )}
      {selectedSymbol && (
        <SymbolDetailPanel
          symbol={selectedSymbol}
          mode={mode}
          onClose={() => setSelectedSymbol(null)}
        />
      )}
    </>
  )
}

function toNum(value: any): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function formatMoney(ccy: string | null, value: number | null): string {
  if (value === null) return '--'
  const formatted = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)
  if (!ccy) return formatted
  return `${ccy} ${formatted}`
}

function formatPct(value: number | null): string {
  if (value === null) return '--'
  return `${value.toFixed(2)}%`
}

function DashboardHeader({
  title,
  tradingMode,
}: {
  title: string
  tradingMode: 'live' | 'demo'
}) {
  const { data: openaiStatus } = useFetch<any>(`/api/account/openai-status`, 60000)
  return (
    <div className="mb-4 flex items-center justify-between">
      <h1 className="text-2xl font-bold terminal-title">{title}</h1>
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 px-3 py-1 bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded text-sm font-bold">
          <span className="inline-block w-2 h-2 bg-amber-400 rounded-full animate-pulse"></span>
          LIVE — Binance
        </div>
        <OpenAIStatusPill status={openaiStatus?.data} />
      </div>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// COMMAND CENTER — centrum dowodzenia "co mam, co działa, gdzie wsadzić kasę"
// ─────────────────────────────────────────────────────────────────────────────

function SystemStatusBar() {
  const { data, loading } = useFetch<any>(`/api/account/system-status`, 20000)
  const d = data?.data
  if (loading && !data) return null

  const stale = d?.data_stale
  const running = d?.collector_running
  const wsOn = d?.ws_running
  const age = d?.last_tick_age_s

  const ageLabel = age == null ? '--'
    : age < 60 ? `${age}s temu`
    : age < 3600 ? `${Math.round(age / 60)} min temu`
    : `${Math.round(age / 3600)}h temu`

  return (
    <div className={`flex items-center gap-4 px-4 py-2 rounded-lg border text-xs mb-5 ${stale ? 'bg-yellow-900/20 border-yellow-600/30' : 'bg-[#0b121a] border-rldc-dark-border/40'}`}>
      <div className="flex items-center gap-1.5">
        <div className={`w-2 h-2 rounded-full ${running ? 'bg-rldc-green-primary animate-pulse' : 'bg-slate-500'}`} />
        <span className="text-slate-400">Kolektor: <span className={running ? 'text-rldc-green-primary' : 'text-slate-500'}>{running ? 'Aktywny' : 'Nieaktywny'}</span></span>
      </div>
      <div className="flex items-center gap-1.5">
        <div className={`w-2 h-2 rounded-full ${wsOn ? 'bg-rldc-teal-primary animate-pulse' : 'bg-slate-600'}`} />
        <span className="text-slate-400">WebSocket: <span className={wsOn ? 'text-rldc-teal-primary' : 'text-slate-500'}>{wsOn ? 'Połączony' : 'Offline'}</span></span>
      </div>
      <div className="flex items-center gap-1.5">
        <div className={`w-2 h-2 rounded-full ${stale ? 'bg-yellow-500' : 'bg-rldc-green-primary'}`} />
        <span className="text-slate-400">Dane: <span className={stale ? 'text-yellow-400' : 'text-rldc-green-primary'}>{stale ? `Nieaktualne (${ageLabel})` : `Żywe (${ageLabel})`}</span></span>
      </div>
      <div className="text-slate-500">Symboli: <span className="text-slate-300">{d?.symbols_with_data ?? '--'}</span></div>
      {d?.last_error_msg && (
        <div className="ml-auto text-rldc-red-primary truncate max-w-[300px]" title={d.last_error_msg}>
          ⚠ {d.last_error_msg}
        </div>
      )}
    </div>
  )
}

// ─── Wykres historii equity portfela ──────────────────────────────────────────
function EquityChartBlock({ kpi, mode }: { kpi: any; mode: 'demo' | 'live' }) {
  const { data: forecast } = useFetch<any>(`/api/portfolio/forecast?mode=${mode}`, 60000)

  const equityHistory: { t: string; equity: number }[] = Array.isArray(kpi?.equity_history) ? kpi.equity_history : []
  const totalEquity: number | null = kpi?.total_equity ?? null
  const equityChange: number | null = kpi?.equity_change ?? null
  const equityChangePct: number | null = kpi?.equity_change_pct ?? null

  const { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } = require('recharts')

  const hasForecast = forecast && !forecast.note
  const f1h = forecast?.forecast_1h ?? null
  const f2h = forecast?.forecast_2h ?? null
  const f7d = forecast?.forecast_7d ?? null

  const fmtPrice = (v: number) => v >= 1000 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)

  return (
    <div className="mb-5 bg-rldc-dark-card border border-rldc-dark-border rounded-xl neon-card overflow-hidden">
      {/* Nagłówek */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-rldc-dark-border/40">
        <div>
          <div className="font-semibold text-slate-100">📈 Wartość portfela</div>
          <div className="text-[11px] text-slate-500 mt-0.5">Historia equity (ostatnie ~48h) · odświeżanie 15s</div>
        </div>
        <div className="text-right">
          {totalEquity != null && (
            <div className="text-lg font-bold font-mono text-rldc-green-primary">{totalEquity.toFixed(2)} EUR</div>
          )}
          {equityChange != null && (
            <div className={`text-xs font-mono ${(equityChange ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>
              {(equityChange ?? 0) >= 0 ? '+' : ''}{equityChange!.toFixed(2)} EUR
              {equityChangePct != null && ` (${equityChangePct >= 0 ? '+' : ''}${equityChangePct.toFixed(2)}%)`}
              <span className="text-slate-500 ml-1">vs 24h temu</span>
            </div>
          )}
        </div>
      </div>

      {/* Wykres */}
      <div className="px-2 pt-3 pb-1">
        {equityHistory.length === 0 ? (
          <div className="flex items-center justify-center h-24 text-xs text-slate-500">
            Brak danych historii equity. Kolektor musi działać ≥15 minut aby pojawił się wykres.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={130}>
            <LineChart data={equityHistory} margin={{ top: 4, right: 10, bottom: 0, left: 0 }}>
              <XAxis
                dataKey="t"
                tick={{ fontSize: 9, fill: '#475569' }}
                interval="preserveStartEnd"
                tickLine={false}
              />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fontSize: 9, fill: '#475569' }}
                tickFormatter={fmtPrice}
                width={52}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{ background: '#0d1b26', border: '1px solid #1e2d3d', fontSize: 10, borderRadius: 6 }}
                formatter={(val: any) => [`${Number(val).toFixed(2)} EUR`, 'Wartość konta']}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Line
                type="monotone"
                dataKey="equity"
                stroke="#00d4aa"
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Prognoza portfela */}
      {(hasForecast || forecast) && (
        <div className="px-5 py-3 border-t border-rldc-dark-border/40 grid grid-cols-3 gap-4">
          {[
            { label: 'Za 1 godzinę', val: f1h, current: totalEquity },
            { label: 'Za 2 godziny', val: f2h, current: totalEquity },
            { label: 'Za 7 dni', val: f7d, current: totalEquity },
          ].map(({ label, val, current }) => {
            if (val == null || current == null) return (
              <div key={label}>
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-0.5">{label}</div>
                <div className="text-sm text-slate-500 font-mono">–</div>
              </div>
            )
            const diff = val - current
            const pct = current > 0 ? (diff / current * 100) : 0
            return (
              <div key={label}>
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-0.5">{label}</div>
                <div className={`text-sm font-bold font-mono ${diff >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>
                  {val.toFixed(2)} EUR
                </div>
                <div className={`text-[11px] font-mono ${diff >= 0 ? 'text-rldc-green-primary/70' : 'text-rldc-red-primary/70'}`}>
                  {diff >= 0 ? '+' : ''}{diff.toFixed(2)} ({pct >= 0 ? '+' : ''}{pct.toFixed(2)}%)
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// TradingStatusPanel — panel "Status handlu / Dlaczego bot nie handluje?"
// Konsumuje /api/account/trading-status i /api/account/capital-snapshot
// ─────────────────────────────────────────────────────────────────────────────
function TradingStatusPanel({ tradingStatus: ts, capitalSnap: cs, mode }: {
  tradingStatus: any
  capitalSnap: any
  mode: 'demo' | 'live'
}) {
  const [expanded, setExpanded] = React.useState(false)

  if (!ts) return null

  const color = ts.status_color === 'green'
    ? { bg: 'bg-rldc-green-primary/8', border: 'border-rldc-green-primary/30', text: 'text-rldc-green-primary', dot: 'bg-rldc-green-primary' }
    : ts.status_color === 'yellow'
    ? { bg: 'bg-yellow-500/8', border: 'border-yellow-500/30', text: 'text-yellow-400', dot: 'bg-yellow-400' }
    : { bg: 'bg-rldc-red-primary/8', border: 'border-rldc-red-primary/30', text: 'text-rldc-red-primary', dot: 'bg-rldc-red-primary' }

  const statusLabel = ts.status_color === 'green'
    ? 'Bot aktywny — może handlować'
    : ts.status_color === 'yellow'
    ? 'Bot aktywny z ograniczeniami'
    : 'Handel zablokowany'

  const blockers: any[] = ts.blockers || []

  return (
    <div className={`mb-5 rounded-lg border ${color.bg} ${color.border} px-4 py-3`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${color.dot} ${ts.status_color === 'green' ? 'animate-pulse' : ''}`} />
          <span className={`text-xs font-bold ${color.text}`}>{statusLabel}</span>
          {blockers.length > 0 && (
            <span className="text-[10px] text-slate-500 ml-1">({blockers.length} blokad{blockers.length === 1 ? 'a' : blockers.length < 5 ? 'y' : 'er'})</span>
          )}
        </div>
        <div className="flex items-center gap-4 text-[10px] text-slate-500">
          <span>{mode.toUpperCase()} | trading: <span className={ts.trading_enabled ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}>{ts.trading_enabled ? 'ON' : 'OFF'}</span></span>
          {ts.last_rejection_reason && (
            <span className="text-yellow-400/70">{ts.last_rejection_reason}</span>
          )}
          <button
            type="button"
            onClick={() => setExpanded(e => !e)}
            className="text-slate-500 hover:text-slate-300 transition text-[10px]"
          >
            {expanded ? '▲ zwiń' : '▼ rozwiń'}
          </button>
        </div>
      </div>

      {/* Blokady — zawsze widoczne gdy są krytyczne lub expanded */}
      {(blockers.length > 0 && (expanded || blockers.some((b: any) => b.severity === 'critical'))) && (
        <div className="mt-3 space-y-1.5">
          {blockers.map((b: any, i: number) => (
            <div key={i} className={`flex items-start gap-2 px-2 py-1.5 rounded text-[10px] ${
              b.severity === 'critical' ? 'bg-rldc-red-primary/10 text-rldc-red-primary border border-rldc-red-primary/20' :
              b.severity === 'warning'  ? 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20' :
              'bg-slate-800 text-slate-400 border border-slate-700'
            }`}>
              <span className="font-mono font-bold shrink-0">{b.code}</span>
              <span>{b.message}</span>
              {b.symbol && <span className="ml-auto text-slate-500 shrink-0">{b.symbol}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Pipeline etapów — widoczny gdy expanded */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-rldc-dark-border/50">
          <div className="text-[10px] text-slate-500 mb-2 uppercase tracking-widest">Pipeline (ostatnie 15 min)</div>
          <div className="flex flex-wrap gap-2">
            {[
              { label: 'Rozważano', value: ts.candidate_count, color: 'text-slate-300' },
              { label: 'Kupiono', value: ts.bought_count_15m, color: 'text-rldc-green-primary' },
              { label: 'Zamknięto', value: ts.closed_count_15m, color: 'text-rldc-red-primary' },
              { label: 'Pominięto', value: ts.skipped_count_15m, color: 'text-yellow-400' },
            ].map(s => (
              <div key={s.label} className="bg-rldc-dark-card rounded px-2 py-1 border border-rldc-dark-border">
                <div className="text-[9px] text-slate-500">{s.label}</div>
                <div className={`text-sm font-bold ${s.color}`}>{s.value ?? '--'}</div>
              </div>
            ))}
          </div>
          {ts.last_decision_time && (
            <div className="mt-2 text-[10px] text-slate-500">
              Ostatnia decyzja: <span className="text-slate-300">{String(ts.last_decision_time).replace('T', ' ').slice(0, 19)}</span>
              {ts.last_attempted_symbol && <> · symbol: <span className="text-rldc-teal-primary">{ts.last_attempted_symbol}</span></>}
            </div>
          )}

          {/* Capital snap — source of truth */}
          {cs && (
            <div className="mt-2 text-[10px] text-slate-500 flex flex-wrap gap-3">
              <span>Źródło: <span className="text-slate-300">{cs.source_of_truth}</span></span>
              <span>Stan: {cs.sync_status === 'ok' ? <span className="text-rldc-green-primary">OK</span> : <span className="text-yellow-400">{cs.sync_status}</span>}</span>
              {cs.sync_warning && <span className="text-yellow-400">⚠ {cs.sync_warning}</span>}
              <span>Aktywne: <span className="text-slate-300">{cs.active_positions_count}</span></span>
              <span>Dust: <span className="text-slate-400">{cs.dust_positions_count}</span></span>
              <span>Cash: <span className="text-slate-300">{cs.cash_assets_count}</span></span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function RuntimeActivityPanel({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading, error } = useFetch<any>(`/api/account/runtime-activity?mode=${mode}`, 10000)
  const rt = data?.data

  if (!rt && loading) {
    return (
      <div className="mb-5 rounded-lg border border-rldc-dark-border bg-rldc-dark-card px-4 py-3 text-xs text-slate-500">
        Ładowanie statusu runtime...
      </div>
    )
  }

  if (error) {
    return (
      <div className="mb-5 rounded-lg border border-rldc-red-primary/30 bg-rldc-red-primary/8 px-4 py-3 text-xs text-rldc-red-primary">
        Błąd runtime-activity: {error}
      </div>
    )
  }

  if (!rt) return null

  const dot = (ok: boolean, warn = false) => (
    <span className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-rldc-green-primary' : warn ? 'bg-yellow-400' : 'bg-rldc-red-primary'}`} />
  )

  const fmtTs = (v: any) => (v ? String(v).replace('T', ' ').slice(0, 19) : '--')
  const lastDecision = rt.last_decision || null
  const lastOrder = rt.last_order || null
  const lastPending = rt.last_pending || null
  const md = rt.market_data || {}
  const worker = rt.worker || {}
  const collector = rt.collector || {}
  const recent: any[] = rt.recent_decisions || []

  return (
    <div className="mb-5 rounded-lg border border-rldc-dark-border bg-rldc-dark-card px-4 py-3">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">Aktywność runtime (LIVE heartbeat)</div>
        <div className={`text-[10px] font-semibold ${rt.alive ? 'text-rldc-green-primary' : 'text-yellow-400'}`}>
          {rt.alive ? 'RUNNING' : 'DEGRADED'}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
        <div className="bg-rldc-dark-bg rounded border border-rldc-dark-border px-2 py-2 text-[10px] text-slate-400 flex items-center justify-between">
          <span>Collector</span>{dot(Boolean(collector.running))}
        </div>
        <div className="bg-rldc-dark-bg rounded border border-rldc-dark-border px-2 py-2 text-[10px] text-slate-400 flex items-center justify-between">
          <span>WebSocket</span>{dot(Boolean(collector.ws_running))}
        </div>
        <div className="bg-rldc-dark-bg rounded border border-rldc-dark-border px-2 py-2 text-[10px] text-slate-400 flex items-center justify-between">
          <span>Worker</span>{dot(Boolean(worker.enabled), !Boolean(worker.running))}
        </div>
        <div className="bg-rldc-dark-bg rounded border border-rldc-dark-border px-2 py-2 text-[10px] text-slate-400 flex items-center justify-between">
          <span>Dane świeże</span>{dot(!Boolean(md.data_stale), Boolean(md.data_stale))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
        <div className="rounded border border-rldc-dark-border bg-rldc-dark-bg px-3 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Ostatnia decyzja</div>
          {lastDecision ? (
            <>
              <div className="text-slate-200 font-mono">{lastDecision.symbol} · {String(lastDecision.action_type || '').toUpperCase()}</div>
              <div className="text-slate-400">{lastDecision.reason_pl || lastDecision.reason_code || '--'}</div>
              <div className="text-slate-500">{fmtTs(lastDecision.timestamp)}</div>
            </>
          ) : <div className="text-slate-500">Brak decyzji</div>}
        </div>

        <div className="rounded border border-rldc-dark-border bg-rldc-dark-bg px-3 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Ostatnie zlecenie</div>
          {lastOrder ? (
            <>
              <div className="text-slate-200 font-mono">{lastOrder.symbol} · {lastOrder.side} · {lastOrder.status}</div>
              <div className="text-slate-400">qty: {Number(lastOrder.quantity || 0).toFixed(6)} · px: {Number(lastOrder.executed_price || 0).toFixed(6)}</div>
              <div className="text-slate-500">{fmtTs(lastOrder.timestamp)}</div>
            </>
          ) : <div className="text-slate-500">Brak zleceń</div>}
        </div>
      </div>

      <div className="mt-3 text-[10px] text-slate-500 flex flex-wrap gap-3">
        <span>Tick age: <span className={md.data_stale ? 'text-yellow-400' : 'text-slate-300'}>{md.last_tick_age_s ?? '--'}s</span></span>
        <span>Symbole z danymi: <span className="text-slate-300">{md.symbols_with_data ?? '--'}</span></span>
        <span>Watchlist: <span className="text-slate-300">{collector.watchlist_count ?? '--'}</span></span>
        <span>Rozważono 15m: <span className="text-slate-300">{rt?.decision_pipeline_15m?.considered ?? 0}</span></span>
        <span>Kupiono 15m: <span className="text-rldc-green-primary">{rt?.decision_pipeline_15m?.bought ?? 0}</span></span>
        <span>Zamknięto 15m: <span className="text-rldc-red-primary">{rt?.decision_pipeline_15m?.closed ?? 0}</span></span>
      </div>

      {lastPending && (
        <div className="mt-2 text-[10px] text-slate-500">
          Ostatni pending: <span className="text-slate-300 font-mono">#{lastPending.id} {lastPending.symbol} {lastPending.side} {lastPending.status}</span>
          <span className="ml-2">{fmtTs(lastPending.created_at)}</span>
        </div>
      )}

      {!!recent.length && (
        <div className="mt-3 pt-3 border-t border-rldc-dark-border/50">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Ostatnie 5 decyzji</div>
          <div className="space-y-1">
            {recent.map((r: any, i: number) => (
              <div key={i} className="text-[10px] text-slate-400 flex items-center justify-between">
                <span className="font-mono text-slate-300">{r.symbol} · {String(r.action_type || '').toUpperCase()}</span>
                <span className="truncate px-2">{r.reason_pl || r.reason_code || '--'}</span>
                <span className="text-slate-500 shrink-0">{fmtTs(r.timestamp)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function CommandCenterView({ mode, onSymbolClick }: { mode: 'demo' | 'live'; onSymbolClick?: (s: string) => void }) {
  const { data: kpi, loading: kpiLoading, lastUpdated: kpiUpdated } = useFetch<any>(`/api/portfolio/wealth?mode=${mode}`, 15000)
  const { data: capitalSnap } = useFetch<any>(`/api/account/capital-snapshot?mode=${mode}`, 20000)
  const { data: tradingStatus } = useFetch<any>(`/api/account/trading-status?mode=${mode}`, 20000)
  // ── Kanoniczny snapshot dashboardu — jeden endpoint, spójny snapshot_id ──
  const { data: marketScanRaw, loading: scanLoading, lastUpdated: scanUpdated } = useFetch<any>(`/api/dashboard/market-scan?mode=${mode}`, 18000)
  const marketScan = (marketScanRaw as any)?.data ?? null
  // Fallback: analiza pozycji z osobnego endpointu
  const { data: analysis, loading: analLoading } = useFetch<any>(`/api/positions/analysis?mode=${mode}`, 30000)
  // Supplemental: szczegółowy status oczekiwania per-symbol (dodatkowe dane diagnostyczne)
  const { data: waitStatus } = useFetch<any>(`/api/signals/wait-status`, 30000)
  const { data: allowedData } = useFetch<any>(`/api/market/allowed-symbols?quotes=EUR,USDC,USDT`, 120000)
  const { data: finalDecisions } = useFetch<any>(`/api/signals/final-decisions?mode=${mode}`, 25000)
  const { data: goalsSummary } = useFetch<any>(`/api/positions/goals-summary?mode=${mode}`, 60000)
  const [expRefreshKey, setExpRefreshKey] = useState(0)
  const { data: expectationsData } = useFetch<any>(`/api/signals/expectations?mode=${mode}&_k=${expRefreshKey}`, 60000)
  const allowedSet: Set<string> = new Set((allowedData?.symbols || []).map((s: any) => s.symbol))
  const hasAllowedData = allowedSet.size > 0
  const [showWaitDetails, setShowWaitDetails] = useState(false)
  const [showFinalDecisions, setShowFinalDecisions] = useState(true)
  const [showExpectations, setShowExpectations] = useState(true)
  const [showExpForm, setShowExpForm] = useState(false)
  const [expFormSymbol, setExpFormSymbol] = useState('')
  const [expFormType, setExpFormType] = useState('target_value_eur')
  const [expFormValue, setExpFormValue] = useState('')
  const [expFormNoBuy, setExpFormNoBuy] = useState(false)
  const [expFormNoSell, setExpFormNoSell] = useState(false)
  const [expFormHorizon, setExpFormHorizon] = useState('7d')
  const [expFormSaving, setExpFormSaving] = useState(false)
  const [expFormMsg, setExpFormMsg] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)
  const [resetMsg, setResetMsg] = useState<string | null>(null)
  const [resetBalance, setResetBalance] = useState('500')
  const [showResetForm, setShowResetForm] = useState(false)
  const [showRejected, setShowRejected] = useState(false)

  const kd = kpi
  const equity = kd?.total_equity ?? null
  const freeCash = kd?.free_cash ?? null
  const inPositions = kd?.positions_value ?? (typeof equity === 'number' && typeof freeCash === 'number' ? equity - freeCash : null)
  const pnlUnrealized = kd?.total_pnl ?? null
  const pnlChange24h = kd?.equity_change ?? null
  const pnlChangePct = kd?.equity_change_pct ?? null

  // Dane ze wspólnego snapshotu — zapewniona spójność snapshot_id
  const snapshotId: string | null = marketScan?.snapshot_id ?? null
  const scanItems: any[] = marketScan?.opportunities_top_n || []
  const bestExec: any = marketScan?.best_executable_candidate ?? null
  const bestAnalytical: any = marketScan?.best_analytical_candidate ?? null
  const rejectedCandidates: any[] = marketScan?.rejected_candidates || []
  const finalStatus: string = marketScan?.final_market_status || 'WAIT'
  const finalMessage: string = marketScan?.final_user_message || ''
  const marketDistribution: any = marketScan?.market_distribution ?? null
  const portfolioConstraints: any = marketScan?.portfolio_constraints_summary ?? null
  // Pozycje z tego samego snapshotu — spójny cycle_id
  const posCardsFromScan: any[] = marketScan?.positions_snapshot || []
  // Fallback: jeśli w skan snapshot brak danych pozycji, użyj pełnego analysis
  const posCards: any[] = posCardsFromScan.length > 0 ? posCardsFromScan : (analysis?.data || [])

  const handleReset = async () => {
    const val = parseFloat(resetBalance.replace(',', '.'))
    if (!Number.isFinite(val) || val <= 0) return
    setResetting(true)
    setResetMsg(null)
    try {
      const res = await fetch(`${getApiBase()}/api/account/demo/reset-balance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ starting_balance: val }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || 'Błąd resetu')
      setResetMsg(`✓ ${json.message}`)
      setShowResetForm(false)
    } catch (e: any) {
      setResetMsg(`✗ ${e.message}`)
    } finally {
      setResetting(false)
    }
  }

  return (
    <div className="flex-1 p-6 overflow-auto">
      {/* Status systemu */}
      <SystemStatusBar />

      {/* Tytuł */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold">Centrum dowodzenia</h1>
          <p className="text-sm text-slate-400 mt-0.5">Stan konta · Najlepsze okazje teraz · Aktywne pozycje</p>
        </div>
        <div className="flex items-center gap-2">
          <DataStatus lastUpdated={kpiUpdated} loading={kpiLoading} error={null} refreshMs={15000} />
          <div className="px-3 py-1 bg-rldc-teal-primary/10 text-rldc-teal-primary rounded text-xs font-medium border border-rldc-teal-primary/20">
            {mode.toUpperCase()}
          </div>
        </div>
      </div>

      {/* KPI — wartość konta */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
        {[
          { label: 'Wartość konta', value: equity != null ? `${equity.toFixed(2)} EUR` : '--', color: 'text-rldc-green-primary' },
          { label: 'Wolne środki', value: freeCash != null ? `${freeCash.toFixed(2)} EUR` : '--', color: 'text-slate-100' },
          { label: 'W pozycjach', value: inPositions != null ? `${inPositions.toFixed(2)} EUR` : '--', color: 'text-slate-100' },
          { label: 'Wynik na pozycjach', value: pnlUnrealized != null ? `${pnlUnrealized >= 0 ? '+' : ''}${pnlUnrealized.toFixed(2)} EUR` : '--', color: pnlColor(pnlUnrealized ?? 0) },
          { label: 'Zmiana 24h', value: pnlChange24h != null ? `${pnlChange24h >= 0 ? '+' : ''}${pnlChange24h.toFixed(2)} EUR (${pnlChangePct?.toFixed(1) ?? '--'}%)` : '--', color: pnlColor(pnlChange24h ?? 0) },
        ].map((k) => (
          <div key={k.label} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">{k.label}</div>
            <div className={`text-lg font-semibold font-mono mt-1 ${k.color}`}>{k.value}</div>
          </div>
        ))}
      </div>

      {/* Info o braku danych live */}
      {kpi?._info && (
        <div className="mb-5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-400 leading-relaxed">
          ⚠ {kpi._info}
        </div>
      )}

      {/* ━━━ PANEL STATUSU HANDLU ━━━ */}
      <TradingStatusPanel tradingStatus={tradingStatus?.data} capitalSnap={capitalSnap?.data} mode={mode} />

      {/* ━━━ AKTYWNOŚĆ RUNTIME (co bot robi teraz) ━━━ */}
      <RuntimeActivityPanel mode={mode} />

      {/* ━━━ NAJLEPSZA OKAZJA TERAZ (best executable candidate) ━━━ */}
      {marketScan && (() => {
        const hasExecutable = finalStatus === 'ENTRY_FOUND' && bestExec != null
        const signalColor = hasExecutable
          ? (bestExec.signal === 'BUY' ? 'text-rldc-green-primary' : 'text-rldc-red-primary')
          : 'text-yellow-400'
        const bgClass = hasExecutable
          ? (bestExec.signal === 'BUY'
              ? 'bg-rldc-green-primary/8 border-rldc-green-primary/30'
              : 'bg-rldc-red-primary/8 border-rldc-red-primary/30')
          : 'bg-slate-500/5 border-slate-500/20'
        const ctaLabel = hasExecutable
          ? (bestExec.signal === 'BUY' ? 'KUP' : 'SPRZEDAJ')
          : 'CZEKAJ'

        return (
          <div className={`mb-5 rounded-xl border-2 px-5 py-4 ${bgClass}`}>
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">
                  Najlepsza okazja teraz
                  {snapshotId && (
                    <span className="ml-2 text-[9px] text-slate-700 font-mono">#{snapshotId.slice(0, 8)}</span>
                  )}
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                  <span className={`text-2xl font-black ${signalColor}`}>{ctaLabel}</span>
                  {hasExecutable && bestExec.symbol && (
                    <span className="text-xl font-bold text-slate-100">
                      {bestExec.symbol.replace('EUR', '/EUR').replace('USDC', '/USDC').replace('USDT', '/USDT')}
                    </span>
                  )}
                  {hasExecutable && bestExec.confidence != null && (
                    <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-rldc-dark-bg border border-rldc-dark-border text-slate-300">
                      {Math.round(bestExec.confidence * 100)}% pewności
                    </span>
                  )}
                  {hasExecutable && bestExec.score != null && (
                    <span className="px-2 py-0.5 rounded-full text-xs bg-rldc-dark-bg border border-rldc-dark-border text-slate-400">
                      Score {bestExec.score.toFixed(1)}/100
                    </span>
                  )}
                </div>

                {/* Powód / opis */}
                {hasExecutable && bestExec.reason && (
                  <div className="text-xs text-slate-500 mt-1 truncate">{bestExec.reason}</div>
                )}
                {!hasExecutable && finalMessage && (
                  <div className="text-xs text-slate-500 mt-1">{finalMessage}</div>
                )}

                {/* Kandydat analityczny vs wykonalny — gdy różne */}
                {!hasExecutable && bestAnalytical && bestAnalytical.symbol !== bestExec?.symbol && (
                  <div className="mt-2 text-xs text-slate-600 border-t border-slate-800 pt-2">
                    <span className="text-slate-500">Najlepszy analitycznie:</span>{' '}
                    <span className="text-slate-400 font-mono">{bestAnalytical.symbol}</span>{' '}
                    <span className="text-slate-500">{bestAnalytical.signal} {bestAnalytical.score?.toFixed(1)}/100</span>
                    {rejectedCandidates.find(r => r.symbol === bestAnalytical.symbol) && (
                      <span className="ml-2 text-rldc-red-primary/70">
                        → zablokowany: {rejectedCandidates.find(r => r.symbol === bestAnalytical.symbol)?.rejection_reason_code}
                      </span>
                    )}
                  </div>
                )}

                {/* Diagnostyka odrzuceń */}
                {rejectedCandidates.length > 0 && (
                  <div className="mt-2">
                    <button
                      className="text-[10px] text-slate-600 hover:text-slate-400 transition"
                      onClick={() => setShowRejected(v => !v)}
                    >
                      {showRejected ? '▲' : '▼'} {rejectedCandidates.length} odrzuconych kandydatów
                    </button>
                    {showRejected && (
                      <div className="mt-1 space-y-1 max-h-40 overflow-auto">
                        {rejectedCandidates.slice(0, 8).map((r: any) => (
                          <div key={r.symbol} className="flex items-center gap-2 text-[10px] text-slate-600">
                            <span className="font-mono text-slate-500 w-20 shrink-0">{r.symbol}</span>
                            <span className={`shrink-0 ${r.signal === 'BUY' ? 'text-rldc-green-primary/60' : 'text-rldc-red-primary/60'}`}>
                              {r.signal}
                            </span>
                            <span className="text-slate-700">{r.rejection_reason_code}</span>
                            <span className="text-slate-700 truncate">{r.rejection_reason_text}</span>
                          </div>
                        ))}
                        {rejectedCandidates.length > 8 && (
                          <div className="text-[10px] text-slate-700">
                            +{rejectedCandidates.length - 8} więcej...
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* CTA button — tylko gdy executable candidate */}
              {hasExecutable && bestExec.symbol && (
                <button
                  onClick={() => onSymbolClick?.(bestExec.symbol)}
                  className={`shrink-0 px-4 py-2 rounded-lg text-sm font-bold border transition ${
                    bestExec.signal === 'BUY'
                      ? 'bg-rldc-green-primary/20 text-rldc-green-primary border-rldc-green-primary/40 hover:bg-rldc-green-primary/35'
                      : 'bg-rldc-red-primary/20 text-rldc-red-primary border-rldc-red-primary/40 hover:bg-rldc-red-primary/35'
                  }`}
                >
                  Otwórz {bestExec.symbol.replace('EUR', '/EUR').replace('USDC', '/USDC')} →
                </button>
              )}
            </div>
          </div>
        )
      })()}

      {/* ━━━ CELE UŻYTKOWNIKA ━━━ */}
      {(() => {
        const exps: any[] = expectationsData?.expectations || []
        const handleSaveExp = async () => {
          setExpFormSaving(true)
          setExpFormMsg(null)
          try {
            const body: any = {
              symbol: expFormSymbol.trim().toUpperCase() || null,
              mode,
              expectation_type: expFormType,
              no_buy: expFormNoBuy,
              no_sell: expFormNoSell,
              preferred_horizon: expFormHorizon,
            }
            if (expFormType === 'target_value_eur') body.target_value_eur = parseFloat(expFormValue)
            else if (expFormType === 'target_price') body.target_price = parseFloat(expFormValue)
            else if (expFormType === 'target_profit_pct') body.target_profit_pct = parseFloat(expFormValue)
            const res = await fetch(`${getApiBase()}/api/signals/expectations`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(body),
            })
            const json = await res.json()
            if (!res.ok) throw new Error(json.detail || 'Błąd')
            setExpFormMsg(`✓ ${json.message}`)
            setShowExpForm(false)
            setExpRefreshKey(k => k + 1)
          } catch (e: any) {
            setExpFormMsg(`✗ ${e.message}`)
          } finally {
            setExpFormSaving(false)
          }
        }
        const handleDeleteExp = async (id: number) => {
          try {
            await fetch(`${getApiBase()}/api/signals/expectations/${id}`, { method: 'DELETE' })
            setExpRefreshKey(k => k + 1)
          } catch {}
        }
        const realismColor = (label: string) =>
          label === 'bardzo_realny' ? 'text-rldc-green-primary' :
          label === 'realny' ? 'text-emerald-400' :
          label === 'umiarkowanie_realny' ? 'text-yellow-400' :
          label === 'trudny' ? 'text-amber-400' : 'text-red-400'
        const realismLabelPl = (label: string) =>
          label === 'bardzo_realny' ? 'Bardzo realny' :
          label === 'realny' ? 'Realny' :
          label === 'umiarkowanie_realny' ? 'Umiarkowanie realny' :
          label === 'trudny' ? 'Trudny' :
          label === 'mało_realny' ? 'Mało realny' : label
        const expTypeLabel = (t: string) =>
          t === 'target_value_eur' ? 'Cel wartości (EUR)' :
          t === 'target_price' ? 'Cel ceny' :
          t === 'target_profit_pct' ? 'Cel zysku (%)' :
          t === 'no_buy' ? 'Zakaz kupna' :
          t === 'no_sell' ? 'Zakaz sprzedaży' : t
        const getGoalAssessment = (expSymbol: string | null) => {
          if (!finalDecisions?.decisions || !expSymbol) return null
          const dec = finalDecisions.decisions.find((d: any) => d.symbol === expSymbol)
          return dec?.goal_assessment || null
        }
        return (
          <div className="mb-5 rounded-xl border border-rldc-dark-border bg-rldc-dark-card/60 overflow-hidden">
            <div
              className="w-full flex items-center justify-between px-5 py-3 hover:bg-white/[0.03] transition cursor-pointer"
              onClick={() => setShowExpectations(v => !v)}
              role="button"
              tabIndex={0}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setShowExpectations(v => !v) }}
            >
              <div className="flex items-center gap-3">
                <span className="text-base">🎯</span>
                <div className="text-left">
                  <div className="text-sm font-semibold text-slate-200">Cele użytkownika</div>
                  <div className="text-[11px] text-slate-500">
                    {exps.length > 0
                      ? `${exps.length} aktywne oczekiwanie${exps.length === 1 ? '' : 'a'} — sterują priorytetem decyzji`
                      : 'Brak aktywnych celów — bot działa na sygnałach technicznych'
                    }
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={e => { e.stopPropagation(); setShowExpForm(v => !v); setShowExpectations(true) }}
                  className="px-2.5 py-1 rounded text-[11px] font-bold bg-rldc-dark-bg border border-rldc-dark-border text-slate-400 hover:text-slate-200 hover:border-slate-500 transition"
                >+ Dodaj cel</button>
                <span className="text-slate-500 text-xs">{showExpectations ? '▲' : '▼'}</span>
              </div>
            </div>

            {showExpectations && (
              <div className="border-t border-rldc-dark-border/40">
                {showExpForm && (
                  <div className="px-5 py-4 bg-rldc-dark-bg/60 border-b border-rldc-dark-border/30">
                    <div className="text-xs font-semibold text-slate-300 mb-3">Nowe oczekiwanie</div>
                    <div className="grid grid-cols-2 gap-3 mb-3">
                      <div>
                        <label className="block text-[10px] text-slate-500 mb-1">Symbol (np. BTCEUR)</label>
                        <input
                          className="w-full bg-slate-800 border border-rldc-dark-border rounded px-2 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-slate-500"
                          placeholder="WLFIEUR"
                          value={expFormSymbol}
                          onChange={e => setExpFormSymbol(e.target.value)}
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-500 mb-1">Typ oczekiwania</label>
                        <select
                          title="Typ oczekiwania"
                          className="w-full bg-slate-800 border border-rldc-dark-border rounded px-2 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-slate-500"
                          onChange={e => setExpFormType(e.target.value)}
                        >
                          <option value="target_value_eur">Cel wartości pozycji w EUR</option>
                          <option value="target_price">Cel ceny symbolu</option>
                          <option value="target_profit_pct">Cel zysku (%)</option>
                          <option value="no_buy">Zakaz kupna</option>
                          <option value="no_sell">Zakaz sprzedaży</option>
                        </select>
                      </div>
                    </div>
                    {['target_value_eur','target_price','target_profit_pct'].includes(expFormType) && (
                      <div className="grid grid-cols-2 gap-3 mb-3">
                        <div>
                          <label className="block text-[10px] text-slate-500 mb-1">
                            {expFormType === 'target_value_eur' ? 'Cel wartości (EUR)' : expFormType === 'target_price' ? 'Cena docelowa (EUR/szt.)' : 'Cel zysku (%)'}
                          </label>
                          <input
                            className="w-full bg-slate-800 border border-rldc-dark-border rounded px-2 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-slate-500"
                            placeholder={expFormType === 'target_profit_pct' ? '8' : '300'}
                            value={expFormValue}
                            onChange={e => setExpFormValue(e.target.value)}
                            type="number"
                          />
                        </div>
                        <div>
                          <label className="block text-[10px] text-slate-500 mb-1">Horyzont czasu</label>
                          <select
                            title="Horyzont czasu"
                            className="w-full bg-slate-800 border border-rldc-dark-border rounded px-2 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-slate-500"
                            onChange={e => setExpFormHorizon(e.target.value)}
                          >
                            <option value="1d">1 dzień</option>
                            <option value="3d">3 dni</option>
                            <option value="7d">7 dni</option>
                            <option value="30d">30 dni</option>
                          </select>
                        </div>
                      </div>
                    )}
                    <div className="flex items-center gap-4 mb-3">
                      <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
                        <input type="checkbox" checked={expFormNoBuy} onChange={e => setExpFormNoBuy(e.target.checked)} className="w-3 h-3" />
                        Zablokuj kupno
                      </label>
                      <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
                        <input type="checkbox" checked={expFormNoSell} onChange={e => setExpFormNoSell(e.target.checked)} className="w-3 h-3" />
                        Zablokuj sprzedaż
                      </label>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleSaveExp}
                        disabled={expFormSaving}
                        className="px-3 py-1.5 rounded bg-rldc-teal-primary/20 text-rldc-teal-primary border border-rldc-teal-primary/30 text-xs font-bold hover:bg-rldc-teal-primary/30 transition disabled:opacity-50"
                      >{expFormSaving ? 'Zapisuję…' : 'Zapisz cel'}</button>
                      <button
                        onClick={() => { setShowExpForm(false); setExpFormMsg(null) }}
                        className="px-3 py-1.5 rounded bg-slate-800 text-slate-400 border border-rldc-dark-border text-xs hover:text-slate-200 transition"
                      >Anuluj</button>
                      {expFormMsg && (
                        <span className={`text-[11px] ml-2 ${expFormMsg.startsWith('✓') ? 'text-rldc-green-primary' : 'text-red-400'}`}>{expFormMsg}</span>
                      )}
                    </div>
                  </div>
                )}
                {exps.length === 0 && !showExpForm && (
                  <div className="px-5 py-4 text-[12px] text-slate-600 text-center">
                    Brak aktywnych celów. Kliknij „+ Dodaj cel" aby ustawić oczekiwanie dla symbolu.
                  </div>
                )}
                {exps.map((exp: any) => {
                  const ga = getGoalAssessment(exp.symbol)
                  return (
                    <div key={exp.id} className="px-5 py-3 border-b border-rldc-dark-border/20 last:border-b-0">
                      <div className="flex items-start gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-1">
                            <span className="font-bold text-sm text-slate-100 font-mono">
                              {exp.symbol ? exp.symbol.replace('EUR','/EUR').replace('USDT','/USDT').replace('USDC','/USDC') : 'Portfel'}
                            </span>
                            <span className="px-2 py-0.5 rounded text-[10px] bg-rldc-dark-bg border border-rldc-dark-border text-slate-400">
                              {expTypeLabel(exp.expectation_type)}
                            </span>
                            {exp.target_value_eur && (
                              <span className="text-[11px] text-blue-400 font-mono">→ {exp.target_value_eur.toFixed(0)} EUR</span>
                            )}
                            {exp.target_price && (
                              <span className="text-[11px] text-blue-400 font-mono">→ {exp.target_price} EUR/szt.</span>
                            )}
                            {exp.target_profit_pct && (
                              <span className="text-[11px] text-blue-400 font-mono">→ +{exp.target_profit_pct}%</span>
                            )}
                            {exp.no_buy && <span className="px-1.5 py-0.5 rounded text-[9px] bg-red-500/10 text-red-400 border border-red-500/20">🚫 kupno</span>}
                            {exp.no_sell && <span className="px-1.5 py-0.5 rounded text-[9px] bg-amber-500/10 text-amber-400 border border-amber-500/20">🚫 sprzedaż</span>}
                            {exp.preferred_horizon && (
                              <span className="text-[10px] text-slate-600">⏱ {exp.preferred_horizon}</span>
                            )}
                          </div>
                          {ga && ga.realism_label && !['brak_pozycji','brak_celu'].includes(ga.realism_label) && (
                            <div className="flex items-center gap-3 flex-wrap mt-1">
                              <span className={`text-[11px] font-semibold ${realismColor(ga.realism_label)}`}>
                                {realismLabelPl(ga.realism_label)}
                              </span>
                              {ga.required_move_pct != null && (
                                <span className="text-[10px] text-slate-500">
                                  {ga.required_move_pct > 0 ? '+' : ''}{ga.required_move_pct}% ruchu potrzeba
                                </span>
                              )}
                              {ga.scenario_base_days != null && (
                                <span className="text-[10px] text-slate-600">
                                  ~{ga.scenario_fast_days}d–{ga.scenario_base_days}d–{ga.scenario_slow_days}d
                                </span>
                              )}
                              {ga.blockers?.length > 0 && (
                                <span className="text-[10px] text-amber-500/80">⚠ {ga.blockers[0]}</span>
                              )}
                            </div>
                          )}
                          {ga?.realism_label === 'brak_pozycji' && (
                            <div className="text-[10px] text-slate-600 mt-1">Brak pozycji — ocena realności niedostępna</div>
                          )}
                        </div>
                        <button
                          onClick={() => handleDeleteExp(exp.id)}
                          className="shrink-0 text-slate-600 hover:text-red-400 text-xs transition px-1 py-0.5"
                          title="Usuń cel"
                        >✕</button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })()}

      {/* ━━━ FINALNA DECYZJA SYSTEMU (6 WARSTW) ━━━ */}
      {finalDecisions?.decisions && finalDecisions.decisions.length > 0 && (
        <div className="mb-5 rounded-xl border border-rldc-dark-border bg-rldc-dark-card/60 overflow-hidden">
          <button
            className="w-full flex items-center justify-between px-5 py-3 hover:bg-white/[0.03] transition"
            onClick={() => setShowFinalDecisions(v => !v)}
          >
            <div className="flex items-center gap-3">
              <span className="text-base">🧠</span>
              <div className="text-left">
                <div className="text-sm font-semibold text-slate-200">Finalna decyzja systemu</div>
                <div className="text-[11px] text-slate-500 flex items-center gap-2 flex-wrap">
                  <span>6 warstw · cel → tier → pozycja → sygnał</span>
                  {((finalDecisions.summary?.sell_at_target || 0) + (finalDecisions.summary?.prepare_exit || 0)) > 0 && (
                    <span className="text-amber-400 font-semibold">
                      ⚡ {(finalDecisions.summary.sell_at_target || 0) + (finalDecisions.summary.prepare_exit || 0)} do wyjścia
                    </span>
                  )}
                  {finalDecisions.summary?.buy_ready > 0 && (
                    <span className="text-rldc-green-primary font-semibold">✓ {finalDecisions.summary.buy_ready} KUP</span>
                  )}
                  {finalDecisions.active_expectations > 0 && (
                    <span className="text-blue-400">🎯 {finalDecisions.active_expectations} cele</span>
                  )}
                </div>
              </div>
            </div>
            <span className="text-slate-500 text-xs">{showFinalDecisions ? '▲' : '▼'}</span>
          </button>

          {showFinalDecisions && (
            <div className="divide-y divide-rldc-dark-border/30 border-t border-rldc-dark-border/40">
              {finalDecisions.decisions.map((d: any) => {
                const action = d.final_action
                const isExitTarget = action === 'SELL_AT_TARGET'
                const isExit = action === 'PREPARE_EXIT' || action === 'PARTIAL_EXIT'
                const isHoldTarget = action === 'HOLD_TARGET'
                const isBuy = action === 'BUY' || action === 'KANDYDAT_DO_WEJŚCIA' || action === 'WEJŚCIE_AKTYWNE'
                const isSell = action === 'SELL'
                const isBlocked = action === 'DO_NOT_ADD' || action === 'WAIT' || action === 'WAIT_FOR_SIGNAL'

                const accentColor =
                  isExitTarget ? 'text-emerald-400' :
                  isExit ? 'text-amber-400' :
                  isHoldTarget ? 'text-blue-400' :
                  isBuy ? 'text-rldc-green-primary' :
                  isSell ? 'text-rldc-red-primary' :
                  isBlocked ? 'text-slate-500' : 'text-slate-400'

                const bgAccent =
                  isExitTarget ? 'bg-emerald-400/5 border-l-2 border-emerald-400/40' :
                  isExit ? 'bg-amber-400/5 border-l-2 border-amber-400/40' :
                  isHoldTarget ? 'bg-blue-400/5 border-l-2 border-blue-400/20' :
                  isBuy ? 'bg-rldc-green-primary/5' :
                  isSell ? 'bg-rldc-red-primary/5' : ''

                const priColorMap: Record<string, string> = {
                  safety: 'text-red-400',
                  user_goal: 'text-emerald-400',
                  portfolio_tier: 'text-blue-400',
                  position_mgmt: 'text-amber-400',
                  symbol_signal: 'text-slate-500',
                }
                const priLabelMap: Record<string, string> = {
                  safety: 'Bezpieczeństwo',
                  user_goal: '🎯 Cel użytkownika',
                  portfolio_tier: 'Tier portfelowy',
                  position_mgmt: 'Zarządzanie pozycją',
                  symbol_signal: 'Sygnał techniczny',
                }

                const pos = d.position_state
                const ga = d.goal_assessment

                return (
                  <div key={d.symbol} className={`px-5 py-3 ${bgAccent}`}>
                    <div className="flex items-center gap-2 flex-wrap mb-1.5">
                      <span className="font-bold text-sm text-slate-100">
                        {d.symbol.replace('EUR','/EUR').replace('USDT','/USDT').replace('USDC','/USDC')}
                      </span>
                      <span className={`px-2 py-0.5 rounded-full text-xs font-black border border-current/30 ${accentColor}`}>
                        {d.final_action_pl}
                      </span>
                      {d.priority_rule && (
                        <span className={`text-[10px] ${priColorMap[d.priority_rule] || 'text-slate-500'}`}>
                          ← {priLabelMap[d.priority_rule] || d.priority_rule}
                        </span>
                      )}
                      {d.blocked_actions?.includes('BUY') && (
                        <span className="text-[9px] text-red-400 border border-red-500/20 px-1.5 rounded">🚫 KUP</span>
                      )}
                    </div>
                    <div className="text-[11px] text-slate-300 mb-1.5 leading-relaxed">{d.final_reason}</div>
                    {d.next_trigger && (
                      <div className="text-[10px] text-slate-500 mb-2 flex items-center gap-1">
                        <span>⏳</span><span>{d.next_trigger}</span>
                      </div>
                    )}
                    {/* Progress bar celu */}
                    {ga && pos?.position_value_eur != null && pos?.hold_target_eur != null && (
                      <div className="mb-2">
                        <div className="flex justify-between text-[9px] mb-0.5">
                          <span className="text-slate-600">Postęp do celu</span>
                          <span className="font-mono">
                            <span className="text-slate-300">{pos.position_value_eur.toFixed(0)}</span>
                            <span className="text-slate-600"> / </span>
                            <span className="text-blue-400">{pos.hold_target_eur.toFixed(0)} EUR</span>
                          </span>
                        </div>
                        <div className="h-1 bg-rldc-dark-bg rounded-full overflow-hidden">
                          <div
                            className={`h-1 rounded-full transition-all ${isExitTarget ? 'bg-emerald-400' : 'bg-blue-400'}`}
                            style={{ width: `${Math.min(100, (pos.position_value_eur / pos.hold_target_eur) * 100)}%` }}
                          />
                        </div>
                        {ga.realism_label && !['brak_pozycji','brak_celu'].includes(ga.realism_label) && (
                          <div className="flex items-center gap-3 mt-1">
                            <span className={`text-[10px] font-medium ${
                              ga.realism_label === 'bardzo_realny' ? 'text-rldc-green-primary' :
                              ga.realism_label === 'realny' ? 'text-emerald-400' :
                              ga.realism_label === 'umiarkowanie_realny' ? 'text-yellow-400' :
                              ga.realism_label === 'trudny' ? 'text-amber-400' : 'text-red-400'
                            }`}>
                              Cel {ga.realism_label === 'bardzo_realny' ? 'bardzo realny' : ga.realism_label === 'realny' ? 'realny' : ga.realism_label === 'umiarkowanie_realny' ? 'umiarkowanie realny' : ga.realism_label === 'trudny' ? 'trudny' : 'mało realny'}
                            </span>
                            {ga.scenario_base_days != null && (
                              <span className="text-[10px] text-slate-600">
                                ~{ga.scenario_fast_days}–{ga.scenario_base_days} dni
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                    {/* 3 micro-pillsy */}
                    <div className="flex flex-wrap gap-1.5">
                      <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800/60 text-[10px]">
                        <span className="text-slate-600">Tech:</span>
                        <span className={
                          d.symbol_analysis?.signal_type === 'BUY' ? 'text-rldc-green-primary font-bold' :
                          d.symbol_analysis?.signal_type === 'SELL' ? 'text-rldc-red-primary font-bold' :
                          'text-slate-500'
                        }>
                          {d.symbol_analysis?.signal_type === 'BUY' ? 'KUP' : d.symbol_analysis?.signal_type === 'SELL' ? 'SPRZEDAJ' : 'TRZYMAJ'}
                        </span>
                        {d.symbol_analysis?.confidence != null && (
                          <span className="text-slate-600">{Math.round(d.symbol_analysis.confidence * 100)}%</span>
                        )}
                        {d.symbol_analysis?.rsi != null && (
                          <span className="text-slate-600">RSI {d.symbol_analysis.rsi}</span>
                        )}
                        <span className="text-slate-700">
                          {d.symbol_analysis?.trend === 'WZROSTOWY' ? '▲' : d.symbol_analysis?.trend === 'SPADKOWY' ? '▼' : '—'}
                        </span>
                      </div>
                      {pos && (
                        <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800/60 text-[10px]">
                          <span className="text-slate-600">Poz:</span>
                          <span className="text-slate-400 font-mono">{(pos.position_value_eur || 0).toFixed(0)} EUR</span>
                          {pos.pnl_pct != null && (
                            <span className={pos.pnl_pct >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}>
                              {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct}%
                            </span>
                          )}
                        </div>
                      )}
                      {d.active_expectation && (
                        <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-blue-900/25 text-[10px] text-blue-400">
                          <span>🎯</span>
                          {d.active_expectation.target_value_eur && <span>{d.active_expectation.target_value_eur.toFixed(0)} EUR</span>}
                          {d.active_expectation.target_profit_pct && <span>+{d.active_expectation.target_profit_pct}%</span>}
                          {d.active_expectation.no_buy && <span className="text-red-400/80 ml-1">🚫kupno</span>}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
      {false && finalDecisions?.decisions && finalDecisions.decisions.length > 0 && (
        <div className="mb-5 rounded-xl border border-rldc-dark-border bg-rldc-dark-card/60 overflow-hidden">
          <button
            className="w-full flex items-center justify-between px-5 py-3 hover:bg-white/[0.03] transition"
            onClick={() => setShowFinalDecisions(v => !v)}
          >
            <div className="flex items-center gap-3">
              <span className="text-base">🧠</span>
              <div className="text-left">
                <div className="text-sm font-semibold text-slate-200">Finalna decyzja systemu</div>
                <div className="text-[11px] text-slate-500">
                  Warstwa portfelowa · analiza symbolu + pozycja + tier
                  {finalDecisions.summary?.prepare_exit > 0 && (
                    <span className="ml-2 text-amber-400 font-semibold">
                      ⚠ {finalDecisions.summary.prepare_exit} do wyjścia
                    </span>
                  )}
                  {finalDecisions.summary?.buy_ready > 0 && (
                    <span className="ml-2 text-rldc-green-primary font-semibold">
                      ✓ {finalDecisions.summary.buy_ready} gotowych do wejścia
                    </span>
                  )}
                </div>
              </div>
            </div>
            <span className="text-slate-500 text-xs">{showFinalDecisions ? '▲' : '▼'}</span>
          </button>

          {showFinalDecisions && (
            <div className="divide-y divide-rldc-dark-border/30 border-t border-rldc-dark-border/40">
              {finalDecisions.decisions.map((d: any) => {
                const action = d.final_action
                const isExit = action === 'PREPARE_EXIT' || action === 'PARTIAL_EXIT'
                const isHoldTarget = action === 'HOLD_TARGET'
                const isBuy = action === 'BUY'
                const isSell = action === 'SELL'
                const isBlocked = action === 'DO_NOT_ADD' || action === 'WAIT'

                const accentColor = isExit ? 'text-amber-400' :
                  isHoldTarget ? 'text-blue-400' :
                  isBuy ? 'text-rldc-green-primary' :
                  isSell ? 'text-rldc-red-primary' :
                  isBlocked ? 'text-slate-500' : 'text-slate-400'

                const bgAccent = isExit ? 'bg-amber-400/5 border-l-2 border-amber-400/40' :
                  isHoldTarget ? 'bg-blue-400/5 border-l-2 border-blue-400/20' :
                  isBuy ? 'bg-rldc-green-primary/5' :
                  isSell ? 'bg-rldc-red-primary/5' : ''

                const priColor: Record<string, string> = {
                  hold_target: 'text-blue-400',
                  position_mgmt: 'text-amber-400',
                  symbol_signal: 'text-slate-500',
                }
                const priLabel: Record<string, string> = {
                  hold_target: 'Tryb TARGET',
                  position_mgmt: 'Zarządzanie pozycją',
                  symbol_signal: 'Sygnał techniczny',
                }

                const pos = d.position_state
                const tier = d.tier_config

                return (
                  <div key={d.symbol} className={`px-5 py-3 ${bgAccent}`}>
                    {/* Nagłówek symbolu */}
                    <div className="flex items-center gap-3 mb-1.5">
                      <span className="font-bold text-sm text-slate-100">
                        {d.symbol.replace('EUR', '/EUR').replace('USDT', '/USDT').replace('USDC', '/USDC')}
                      </span>
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-black ${accentColor} bg-current/10`}
                        style={{ backgroundColor: 'transparent', border: '1px solid currentcolor', opacity: 1 }}>
                        <span className={accentColor}>{d.final_action_pl}</span>
                      </span>
                      <span className={`text-[10px] ml-auto ${priColor[d.priority_rule] || 'text-slate-500'}`}>
                        {priLabel[d.priority_rule] || d.priority_rule}
                      </span>
                    </div>

                    {/* Finalne uzasadnienie */}
                    <div className="text-[11px] text-slate-300 mb-2 ml-1">{d.final_reason}</div>

                    {/* Następny trigger */}
                    {d.next_trigger && (
                      <div className="text-[10px] text-slate-500 mb-2 ml-1 flex items-center gap-1">
                        <span>⏳</span><span>{d.next_trigger}</span>
                      </div>
                    )}

                    {/* Trzy warstwy w kompaktowych pillach */}
                    <div className="flex flex-wrap gap-2 ml-1">
                      {/* Warstwa 1: Sygnał symbolu */}
                      <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/60 text-[10px]">
                        <span className="text-slate-500">Techniczny:</span>
                        <span className={
                          d.symbol_analysis?.signal_type === 'BUY' ? 'text-rldc-green-primary font-bold' :
                          d.symbol_analysis?.signal_type === 'SELL' ? 'text-rldc-red-primary font-bold' :
                          'text-slate-400'
                        }>
                          {d.symbol_analysis?.signal_type === 'BUY' ? 'KUP' :
                           d.symbol_analysis?.signal_type === 'SELL' ? 'SPRZEDAJ' : 'TRZYMAJ'}
                        </span>
                        <span className="text-slate-500">{d.symbol_analysis?.confidence != null ? `${Math.round(d.symbol_analysis.confidence * 100)}%` : ''}</span>
                        {d.symbol_analysis?.rsi != null && <span className="text-slate-500">RSI {d.symbol_analysis.rsi}</span>}
                        <span className="text-slate-600">{d.symbol_analysis?.trend === 'WZROSTOWY' ? '▲' : d.symbol_analysis?.trend === 'SPADKOWY' ? '▼' : '—'}</span>
                      </div>

                      {/* Warstwa 2: Stan pozycji */}
                      {pos && (
                        <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/60 text-[10px]">
                          <span className="text-slate-500">Pozycja:</span>
                          <span className="text-slate-300 font-mono">{pos.quantity} szt.</span>
                          {pos.pnl_pct != null && (
                            <span className={pos.pnl_pct >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}>
                              {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct}%
                            </span>
                          )}
                          {pos.position_value_eur != null && (
                            <span className="text-slate-400">{pos.position_value_eur.toFixed(0)} EUR</span>
                          )}
                          {pos.distance_to_target_pct != null && (
                            <span className="text-blue-400">→ cel {pos.distance_to_target_pct > 0 ? `-${pos.distance_to_target_pct}%` : '✓'}</span>
                          )}
                        </div>
                      )}

                      {/* Warstwa 3: Tier/portfel */}
                      {tier?.hold_mode && (
                        <div className="flex items-center gap-1 px-2 py-1 rounded bg-blue-900/30 text-[10px] text-blue-300">
                          <span>🎯</span>
                          <span>Target: {tier.target_value_eur?.toFixed(0)} EUR</span>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ━━━ NA CO SYSTEM CZEKA ━━━ */}
      {waitStatus?.items && waitStatus.items.length > 0 && (
        <div className="mb-5 rounded-xl border border-rldc-dark-border bg-rldc-dark-card/60 overflow-hidden">
          <button
            className="w-full flex items-center justify-between px-5 py-3 hover:bg-white/[0.03] transition"
            onClick={() => setShowWaitDetails(v => !v)}
          >
            <div className="flex items-center gap-3">
              <span className="text-base">🔍</span>
              <div className="text-left">
                <div className="text-sm font-semibold text-slate-200">Na co system czeka?</div>
                <div className="text-[11px] text-slate-500">
                  {waitStatus.summary?.ready > 0
                    ? `${waitStatus.summary.ready} gotowych do wejścia · ${waitStatus.summary.waiting} czeka na warunki`
                    : `${waitStatus.summary?.waiting ?? waitStatus.items.length} symbol${waitStatus.summary?.waiting === 1 ? '' : 'i'} czeka na spełnienie warunków`}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {waitStatus.summary?.ready > 0 && (
                <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-rldc-green-primary/20 text-rldc-green-primary border border-rldc-green-primary/30">
                  {waitStatus.summary.ready} GOTOWE
                </span>
              )}
              <span className="text-slate-500 text-xs">{showWaitDetails ? '▲' : '▼'}</span>
            </div>
          </button>
          {showWaitDetails && (
            <div className="divide-y divide-rldc-dark-border/30 border-t border-rldc-dark-border/40">
              {waitStatus.items.map((item: any) => {
                const isReady = item.status === 'READY'
                const isClose = !isReady && item.score >= (waitStatus.min_score - 1.5)
                const isAllowed = !hasAllowedData || allowedSet.has(item.symbol)
                return (
                  <div key={item.symbol} className={`px-5 py-3 ${isReady ? 'bg-rldc-green-primary/5' : ''} ${!isAllowed ? 'opacity-60' : ''}`}>
                    <div className="flex items-center gap-3 mb-2">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${isReady ? 'bg-rldc-green-primary' : isClose ? 'bg-yellow-400' : 'bg-slate-600'}`} />
                      <span className="font-bold text-sm text-slate-100">
                        {item.symbol.replace('EUR', '/EUR').replace('USDT', '/USDT')}
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        item.signal_type === 'BUY' ? 'bg-rldc-green-primary/20 text-rldc-green-primary' :
                        item.signal_type === 'SELL' ? 'bg-rldc-red-primary/20 text-rldc-red-primary' :
                        'bg-slate-500/20 text-slate-400'
                      }`}>
                        {item.action_pl}
                      </span>
                      {hasAllowedData && (
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${isAllowed ? 'bg-rldc-green-primary/10 text-rldc-green-primary/70' : 'bg-red-500/15 text-red-400'}`}>
                          {isAllowed ? '✓ SPOT' : '✗ niedozwolony'}
                        </span>
                      )}
                      <span className={`text-[11px] ml-auto ${isReady ? 'text-rldc-green-primary' : isClose ? 'text-yellow-400' : 'text-slate-500'}`}>
                        {item.status_pl}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 ml-5 mb-2">
                      {/* Confidence */}
                      <div>
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-[10px] text-slate-500">Pewność</span>
                          <span className={`text-[10px] font-mono ${item.confidence >= item.confidence_min ? 'text-rldc-green-primary' : 'text-slate-400'}`}>
                            {Math.round(item.confidence * 100)}% / min {Math.round(item.confidence_min * 100)}%
                          </span>
                        </div>
                        <div className="relative h-1 bg-rldc-dark-bg rounded-full overflow-hidden">
                          <div className="absolute inset-y-0 left-0 bg-slate-600/50 rounded-full" style={{ width: `${Math.round(item.confidence_min * 100)}%` }} />
                          <div
                            className={`absolute inset-y-0 left-0 rounded-full transition-all ${item.confidence >= item.confidence_min ? 'bg-rldc-green-primary' : 'bg-yellow-500'}`}
                            style={{ width: `${Math.min(100, Math.round(item.confidence * 100))}%` }}
                          />
                        </div>
                      </div>
                      {/* Score */}
                      <div>
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-[10px] text-slate-500">Score</span>
                          <span className={`text-[10px] font-mono ${item.score >= item.score_min ? 'text-rldc-green-primary' : 'text-slate-400'}`}>
                            {item.score.toFixed(1)} / min {item.score_min.toFixed(1)}
                          </span>
                        </div>
                        <div className="relative h-1 bg-rldc-dark-bg rounded-full overflow-hidden">
                          <div className="absolute inset-y-0 left-0 bg-slate-600/50 rounded-full" style={{ width: `${(item.score_min / 10) * 100}%` }} />
                          <div
                            className={`absolute inset-y-0 left-0 rounded-full transition-all ${item.score >= item.score_min ? 'bg-rldc-green-primary' : isClose ? 'bg-yellow-500' : 'bg-slate-500'}`}
                            style={{ width: `${Math.min(100, (item.score / 10) * 100)}%` }}
                          />
                        </div>
                      </div>
                    </div>
                    {/* Brakujące warunki */}
                    {item.missing_conditions?.length > 0 && (
                      <div className="ml-5 space-y-0.5">
                        {item.missing_conditions.map((c: any, ci: number) => (
                          <div key={ci} className="flex items-center gap-1.5 text-[10px] text-slate-500">
                            <span className="text-red-400">✗</span>
                            <span className="text-slate-400">{c.condition}:</span>
                            <span className="text-slate-300 font-mono">{c.current}</span>
                            <span className="text-slate-600">→ wymagane:</span>
                            <span className="text-rldc-green-primary/70 font-mono">{c.required}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {/* Info RSI + trend + cena */}
                    <div className="ml-5 mt-1.5 flex items-center gap-4 text-[10px] text-slate-600">
                      {item.rsi != null && <span>RSI <span className="text-slate-400 font-mono">{item.rsi}</span></span>}
                      {item.trend !== 'BRAK DANYCH' && <span>Trend <span className="text-slate-400">{item.trend}</span></span>}
                      {item.price != null && <span>Cena <span className="text-slate-400 font-mono">{item.price < 1 ? item.price.toFixed(6) : item.price.toFixed(4)} EUR</span></span>}
                      {item.expected_profit_pct != null && <span>E(zysk) <span className="text-rldc-green-primary font-mono">+{(item.expected_profit_pct * 100).toFixed(1)}%</span></span>}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ━━━ WYKRES PORTFELA (Historia equity) ━━━ */}
      <EquityChartBlock kpi={kpi} mode={mode} />

      <div className="grid grid-cols-12 gap-5">
        {/* Lewa kolumna: TOP okazje + pozycje */}
        <div className="col-span-12 lg:col-span-7 space-y-5">

          {/* TOP okazje — Market Scanner */}
          <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border neon-card overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-rldc-dark-border/40">
              <div>
                <div className="font-semibold text-slate-100">🔥 Najlepsze okazje teraz</div>
                <div className="text-[11px] text-slate-500 mt-0.5">TOP 5 par wg analizy technicznej (RSI + EMA + ATR)</div>
              </div>
              {scanLoading && <div className="text-[10px] text-slate-500">Analizuję…</div>}
            </div>
            <div className="divide-y divide-rldc-dark-border/30">
              {scanItems.length === 0 && !scanLoading && (
                <EmptyState reason="no-data" detail="Brak danych rynkowych do analizy. Upewnij się, że collector działa." />
              )}
              {scanItems.map((s: any, i: number) => {
                const isStrong = s.confidence >= 0.75
                const isAllowed = !hasAllowedData || allowedSet.has(s.symbol)
                return (
                  <div key={s.symbol} className={`flex items-center gap-4 px-5 py-3 hover:bg-white/[0.04] transition cursor-pointer ${!isAllowed ? 'opacity-60' : ''}`} onClick={() => onSymbolClick?.(s.symbol)}>
                    <div className="w-6 text-center text-slate-500 text-sm font-mono">{i + 1}</div>
                    <div className="w-28">
                      <div className="font-bold text-slate-100">{s.symbol.replace('EUR', '/EUR').replace('USDC', '/USDC')}</div>
                      <div className="text-[11px] text-slate-500">{s.trend === 'WZROSTOWY' ? '▲ Wzrost' : s.trend === 'SPADKOWY' ? '▼ Spadek' : '— Boczny'}</div>
                    </div>
                    <div className={`px-3 py-1 rounded-full text-xs font-bold ${
                      s.signal === 'BUY' ? 'bg-rldc-green-primary/20 text-rldc-green-primary' :
                      s.signal === 'SELL' ? 'bg-rldc-red-primary/20 text-rldc-red-primary' :
                      'bg-slate-500/20 text-slate-400'
                    }`}>
                      {s.signal === 'BUY' ? 'KUP' : s.signal === 'SELL' ? 'SPRZEDAJ' : 'OBSERWUJ'}
                    </div>
                    <div className="flex-1">
                      {/* Confidence bar */}
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-rldc-dark-bg rounded-full h-1.5">
                          <div
                            className={`h-1.5 rounded-full ${s.signal === 'BUY' ? 'bg-rldc-green-primary' : s.signal === 'SELL' ? 'bg-rldc-red-primary' : 'bg-slate-500'}`}
                            style={{ width: `${Math.round(s.confidence * 100)}%` }}
                          />
                        </div>
                        <span className={`text-xs font-mono ${isStrong ? 'text-slate-100' : 'text-slate-400'}`}>
                          {Math.round(s.confidence * 100)}%
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs font-mono text-slate-300">{s.price != null ? (s.price < 1 ? s.price.toFixed(6) : s.price < 100 ? s.price.toFixed(4) : s.price.toFixed(2)) : '--'} EUR</div>
                      {s.rsi != null && <div className="text-[10px] text-slate-500">RSI {s.rsi}</div>}
                      {hasAllowedData && (
                        <div className={`text-[9px] font-bold mt-0.5 ${isAllowed ? 'text-rldc-green-primary/70' : 'text-red-400'}`}>
                          {isAllowed ? '✓ SPOT OK' : '✗ niedozwolony'}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
            {scanItems.length > 0 && (
              <div className="px-5 py-2 border-t border-rldc-dark-border/30">
                <div className="text-[10px] text-slate-500">
                  Przeskanowano {marketScan?.scanned_symbols_count ?? '--'} symboli,
                  przeanalizowano {marketScan?.analyzed_symbols_count ?? '--'} ·
                  snapshot #{snapshotId?.slice(0, 8) ?? '--'} · odświeżanie 18s
                </div>
              </div>
            )}
          </div>

          {/* Na jakie cele teraz pracuje system? */}
          {goalsSummary && (goalsSummary.data?.length ?? 0) > 0 && (
            <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border neon-card overflow-hidden mb-5">
              <div className="flex items-center justify-between px-5 py-3 border-b border-rldc-dark-border/40">
                <div>
                  <div className="font-semibold text-slate-100">🎯 Na jakie cele teraz pracuje system?</div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    {goalsSummary.count} aktywn{goalsSummary.count === 1 ? 'y cel' : 'e cele'} — AI ocena realności i zaleceń
                  </div>
                </div>
              </div>
              <div className="divide-y divide-rldc-dark-border/30">
                {(goalsSummary.data as any[]).map((g: any) => {
                  const scoreColor = (s: number) =>
                    s >= 80 ? 'text-rldc-green-primary' :
                    s >= 60 ? 'text-emerald-400' :
                    s >= 40 ? 'text-yellow-400' :
                    s >= 20 ? 'text-orange-400' : 'text-rldc-red-primary'
                  const decColor = (d: string) =>
                    d === 'sprzedaj_teraz' ? 'text-rldc-green-primary' :
                    d === 'zmień_cel' ? 'text-yellow-400' :
                    d === 'rozważ_zamknięcie' ? 'text-rldc-red-primary' : 'text-rldc-teal-primary'
                  const decLabel = (d: string) =>
                    d === 'sprzedaj_teraz' ? '✓ SPRZEDAJ' :
                    d === 'zmień_cel' ? '↕ ZMIEŃ CEL' :
                    d === 'rozważ_zamknięcie' ? '⚠ ZAMKNIJ?' : '→ CZEKAJ'
                  return (
                    <div
                      key={g.symbol}
                      className="px-5 py-3 hover:bg-white/[0.04] transition cursor-pointer"
                      onClick={() => onSymbolClick?.(g.symbol)}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <span className="font-bold text-slate-100">{g.symbol}</span>
                          <span className="text-xs text-slate-400 font-mono">→ {g.goal_value?.toFixed(2)} EUR</span>
                          {g.goal_label && <span className="text-[10px] text-slate-600 italic">{g.goal_label}</span>}
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="text-right">
                            <div className={`text-xs font-bold ${scoreColor(g.goal_reality_score ?? 50)}`}>
                              {g.goal_reality_label_pl}
                            </div>
                            <div className="text-[9px] text-slate-600">{g.goal_reality_score}/100</div>
                          </div>
                          <div className={`text-xs font-bold ${decColor(g.goal_decision)}`}>
                            {decLabel(g.goal_decision)}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-4 mt-1.5">
                        {/* Pasek postępu */}
                        <div className="flex-1 h-1 bg-rldc-dark-bg rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              (g.goal_reality_score ?? 0) >= 60 ? 'bg-rldc-green-primary' :
                              (g.goal_reality_score ?? 0) >= 40 ? 'bg-yellow-400' : 'bg-rldc-red-primary'
                            }`}
                            style={{ width: `${g.goal_reality_score ?? 0}%` }}
                          />
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          {g.needed_move_eur != null && (
                            <span className={`text-[10px] font-mono ${g.needed_move_eur > 0 ? 'text-slate-400' : 'text-rldc-green-primary'}`}>
                              {g.needed_move_eur > 0 ? `+${g.needed_move_eur.toFixed(2)} EUR do celu` : `Cel osiągnięty!`}
                            </span>
                          )}
                          {g.eta_label && (
                            <span className="text-[10px] text-slate-500">ETA: {g.eta_label}</span>
                          )}
                          {g.trend && (
                            <span className={`text-[10px] ${g.trend === 'WZROSTOWY' ? 'text-rldc-green-primary' : g.trend === 'SPADKOWY' ? 'text-rldc-red-primary' : 'text-slate-500'}`}>
                              {g.trend}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Aktywne pozycje — skrócone karty */}
          <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border neon-card overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-rldc-dark-border/40">
              <div>
                <div className="font-semibold text-slate-100">Aktywne pozycje</div>
                <div className="text-[11px] text-slate-500 mt-0.5">Decyzja systemu dla każdej otwartej pozycji</div>
              </div>
              {analLoading && <div className="text-[10px] text-slate-500">Analiza…</div>}
            </div>
            <div className="divide-y divide-rldc-dark-border/30">
              {posCards.length === 0 && !analLoading && (
                <EmptyState reason="no-data" detail="Brak otwartych pozycji." />
              )}
              {posCards.map((c: any) => (
                <div key={c.symbol} className="px-5 py-3 hover:bg-white/[0.04] transition cursor-pointer" onClick={() => onSymbolClick?.(c.symbol)}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-100">{c.symbol}</span>
                      {c.is_hold && <span className="text-[10px] px-1.5 py-0.5 rounded bg-rldc-orange-primary/20 text-rldc-orange-primary">HOLD</span>}
                    </div>
                    <div className={`px-3 py-0.5 rounded text-xs font-bold ${decisionBg(c.decision)}`}>
                      <span className={decisionColor(c.decision)}>{c.decision}</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-xs">
                    <div>
                      <div className="text-slate-500">Kupiono</div>
                      <div className="font-mono text-slate-200">{c.entry_price?.toFixed(c.entry_price > 10 ? 2 : 6)}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Teraz</div>
                      <div className="font-mono text-slate-200">{c.current_price?.toFixed(c.current_price > 10 ? 2 : 6)}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Wartość</div>
                      <div className="font-mono text-slate-200">{c.position_value_eur?.toFixed(2)} EUR</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Wynik EUR</div>
                      <div className={`font-mono font-bold ${pnlColor(c.pnl_eur)}`}>{c.pnl_eur >= 0 ? '+' : ''}{c.pnl_eur?.toFixed(2)}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Wynik %</div>
                      <div className={`font-mono font-bold ${pnlColor(c.pnl_pct)}`}>{c.pnl_pct >= 0 ? '+' : ''}{c.pnl_pct?.toFixed(1)}%</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Trend / RSI</div>
                      <div className="font-mono text-slate-400">{c.trend === 'WZROSTOWY' ? '▲' : c.trend === 'SPADKOWY' ? '▼' : '—'} {c.rsi ?? '--'}</div>
                    </div>
                  </div>
                  {c.reasons?.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
                      {c.reasons.slice(0, 2).map((r: string, i: number) => (
                        <span key={i} className="text-[10px] text-slate-500 leading-relaxed flex items-center gap-1">
                          <span className="text-rldc-teal-primary/50">•</span>
                          {r}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Prawa kolumna: co teraz zrobić + reset demo */}
        <div className="col-span-12 lg:col-span-5 space-y-5">

          {/* Priorytetowa decyzja — Best Executable Candidate */}
          <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border neon-card p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Najlepsza okazja teraz</div>
              <DataStatus lastUpdated={scanUpdated} loading={scanLoading} error={null} refreshMs={18000} />
            </div>

            {scanLoading && !marketScan && (
              <div className="py-3 text-center text-sm text-slate-500">Analizuję rynek…</div>
            )}

            {marketScan && finalStatus === 'ENTRY_FOUND' && bestExec && (() => {
              const opp = bestExec
              const isBuy = opp.signal === 'BUY'
              const hasProfit = opp.expected_profit_pct != null && opp.risk_pct != null
              const rrRatio = hasProfit ? (opp.expected_profit_pct / opp.risk_pct).toFixed(1) : null
              const accentBg = isBuy ? 'bg-rldc-green-primary/10 border-rldc-green-primary/30' : 'bg-rldc-red-primary/10 border-rldc-red-primary/30'
              const accentText = isBuy ? 'text-rldc-green-primary' : 'text-rldc-red-primary'
              const accentBar = isBuy ? 'bg-rldc-green-primary' : 'bg-rldc-red-primary'
              return (
                <div
                  className={`rounded-lg border p-4 cursor-pointer hover:opacity-90 transition ${accentBg}`}
                  onClick={() => onSymbolClick?.(opp.symbol)}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className={`text-2xl font-black ${accentText}`}>{opp.symbol.replace('EUR', '/EUR').replace('USDC', '/USDC')}</div>
                      <div className={`px-3 py-1 rounded-full text-sm font-bold ${accentText} border ${isBuy ? 'border-rldc-green-primary/40' : 'border-rldc-red-primary/40'}`}>
                        {isBuy ? '↑ KUP' : '↓ SPRZEDAJ'}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-xl font-black font-mono ${accentText}`}>{Math.round(opp.confidence * 100)}%</div>
                      <div className="text-[10px] text-slate-500">pewność</div>
                    </div>
                  </div>
                  <div className="w-full bg-rldc-dark-bg rounded-full h-1.5 mb-3">
                    <div className={`h-1.5 rounded-full ${accentBar}`} style={{ width: `${Math.round(opp.confidence * 100)}%` }} />
                  </div>
                  {hasProfit && (
                    <div className="grid grid-cols-3 gap-3 mb-3 text-center">
                      <div>
                        <div className="text-rldc-green-primary text-base font-bold font-mono">+{opp.expected_profit_pct}%</div>
                        <div className="text-[10px] text-slate-500">szac. zysk</div>
                      </div>
                      <div>
                        <div className="text-rldc-red-primary text-base font-bold font-mono">-{opp.risk_pct}%</div>
                        <div className="text-[10px] text-slate-500">ryzyko stop</div>
                      </div>
                      <div>
                        <div className={`text-base font-bold font-mono ${parseFloat(rrRatio ?? '0') >= 1.5 ? 'text-rldc-teal-primary' : 'text-slate-400'}`}>
                          {rrRatio}:1
                        </div>
                        <div className="text-[10px] text-slate-500">R/R ratio</div>
                      </div>
                    </div>
                  )}
                  <div className="flex items-center gap-2 mb-2">
                    <div className={`text-sm font-bold font-mono ${accentText}`}>Score {opp.score?.toFixed(1)}</div>
                    <div className="flex-1 h-px bg-rldc-dark-border/50" />
                    {opp.price && <div className="text-xs font-mono text-slate-400">{opp.price < 1 ? opp.price.toFixed(6) : opp.price < 100 ? opp.price.toFixed(4) : opp.price.toFixed(2)} EUR</div>}
                  </div>
                  {opp.score_breakdown?.length > 0 && (
                    <ul className="mt-1 space-y-1 list-none p-0">
                      {(opp.score_breakdown as string[]).map((line: string, i: number) => (
                        <li key={i} className={`flex items-start gap-1.5 text-[10px] leading-relaxed ${
                          line.startsWith('+') ? 'text-slate-300' : line.startsWith('-') ? 'text-rldc-red-primary/70' : 'text-slate-500'
                        }`}>
                          <span className="mt-0.5 shrink-0">{line.startsWith('+') ? '●' : line.startsWith('-') ? '○' : '·'}</span>
                          <span>{line}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {/* Snapshot ID dla spójności */}
                  {snapshotId && (
                    <div className="mt-2 text-[9px] text-slate-700 font-mono">snapshot #{snapshotId.slice(0, 8)}</div>
                  )}
                </div>
              )
            })()}

            {marketScan && finalStatus !== 'ENTRY_FOUND' && (
              <div className="rounded-lg border border-rldc-dark-border/50 bg-slate-500/5 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="text-slate-300 font-semibold text-sm">⏸ Czekaj</div>
                  {bestAnalytical && (
                    <div className="text-[10px] px-2 py-0.5 rounded bg-slate-500/20 text-slate-400 font-mono">
                      analitycznie: {bestAnalytical.symbol} {bestAnalytical.signal} {(bestAnalytical.confidence * 100).toFixed(0)}%
                    </div>
                  )}
                </div>
                <div className="text-xs text-slate-400 leading-relaxed">{finalMessage || 'Analizuję rynek…'}</div>
                <div className="text-[10px] text-slate-500 mt-2">
                  Przeskanowano {marketScan.scanned_symbols_count ?? '--'} symboli,
                  odrzucono {marketScan.rejected_count ?? '--'} kandydatów
                </div>
                {rejectedCandidates.slice(0, 3).map((r: any) => (
                  <div key={r.symbol} className="mt-1 text-[10px] text-slate-600 flex gap-2">
                    <span className="font-mono text-slate-500">{r.symbol}</span>
                    <span className="text-rldc-red-primary/60">{r.rejection_reason_code}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Best analytical ≠ executable — pokaż różnicę */}
            {marketScan && bestExec && bestAnalytical && bestExec.symbol !== bestAnalytical.symbol && (
              <div className="mt-3 pt-3 border-t border-rldc-dark-border/40">
                <div className="text-[10px] text-slate-500 mb-1">Następna w kolejce</div>
                <div
                  className="flex items-center gap-3 cursor-pointer hover:opacity-80 transition"
                  onClick={() => onSymbolClick?.(bestAnalytical.symbol)}
                >
                  <div className="text-sm font-bold text-slate-300">{bestAnalytical.symbol.replace('EUR', '/EUR')}</div>
                  <div className={`px-2 py-0.5 rounded text-[11px] font-bold ${bestAnalytical.signal === 'BUY' ? 'text-rldc-green-primary bg-rldc-green-primary/10' : 'text-rldc-red-primary bg-rldc-red-primary/10'}`}>
                    {bestAnalytical.signal === 'BUY' ? 'KUP' : 'SPRZEDAJ'}
                  </div>
                  <div className="text-xs font-mono text-slate-400">{(bestAnalytical.confidence * 100).toFixed(0)}% · {bestAnalytical.score?.toFixed(1)}pkt</div>
                </div>
              </div>
            )}
          </div>

          {/* Podsumowanie skanera */}
          {scanItems.length > 0 && (
            <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border neon-card p-5">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">Rozkład rynku</div>
              <div className="flex gap-4">
                {[
                  { label: 'BUY', count: scanItems.filter((s: any) => s.signal === 'BUY').length, color: 'text-rldc-green-primary', bg: 'bg-rldc-green-primary' },
                  { label: 'HOLD', count: scanItems.filter((s: any) => s.signal === 'HOLD').length, color: 'text-slate-400', bg: 'bg-slate-500' },
                  { label: 'SELL', count: scanItems.filter((s: any) => s.signal === 'SELL').length, color: 'text-rldc-red-primary', bg: 'bg-rldc-red-primary' },
                ].map((b) => (
                  <div key={b.label} className="flex-1 text-center">
                    <div className={`text-2xl font-bold ${b.color}`}>{b.count}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">{b.label}</div>
                    <div className="mt-1 h-1 rounded-full bg-rldc-dark-bg">
                      <div className={`h-1 rounded-full ${b.bg}`} style={{ width: `${marketScan?.analyzed_symbols_count ? Math.round(b.count / marketScan.analyzed_symbols_count * 100) : 0}%` }} />
                    </div>
                  </div>
                ))}
              </div>
              <div className="text-[10px] text-slate-500 text-center mt-2">z {marketScan?.scanned_symbols_count ?? '--'} przeskanowanych par</div>
            </div>
          )}

          {/* Reset Demo — ukryty w trybie live (nieużywany) */}
          {false && mode === 'demo' && (
            <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border/50 neon-card p-5">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">Reset konta demo</div>
              <p className="text-xs text-slate-400 mb-3">Zresetuj konto demo do wybranego kapitału startowego. Zamknie wszystkie pozycje i wyczyści historię snapshotów.</p>
              {!showResetForm ? (
                <button
                  onClick={() => setShowResetForm(true)}
                  className="w-full px-4 py-2 rounded-lg text-sm font-semibold bg-rldc-orange-primary/15 text-rldc-orange-primary border border-rldc-orange-primary/30 hover:bg-rldc-orange-primary/25 transition"
                >
                  Resetuj demo
                </button>
              ) : (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={resetBalance}
                      onChange={(e) => setResetBalance(e.target.value)}
                      className="flex-1 px-3 py-1.5 text-sm rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 font-mono"
                      placeholder="500"
                    />
                    <span className="text-sm text-slate-400">EUR</span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={handleReset}
                      disabled={resetting}
                      className="flex-1 px-4 py-2 rounded text-sm font-semibold bg-rldc-orange-primary/20 text-rldc-orange-primary border border-rldc-orange-primary/30 hover:bg-rldc-orange-primary/35 disabled:opacity-50 transition"
                    >
                      {resetting ? 'Resetuję…' : 'Potwierdź reset'}
                    </button>
                    <button
                      onClick={() => { setShowResetForm(false); setResetMsg(null) }}
                      className="px-3 py-2 rounded text-sm text-slate-400 border border-rldc-dark-border hover:bg-slate-500/10 transition"
                    >
                      Anuluj
                    </button>
                  </div>
                </div>
              )}
              {resetMsg && (
                <div className={`mt-2 text-xs ${(resetMsg?.startsWith('✓')) ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>
                  {resetMsg}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Aktywność bota — ostatnie 15 minut ───────────────────────────────────────
function BotActivityBlock({ mode }: { mode: string }) {
  const { data, loading } = useFetch<any>(`/api/account/bot-activity?mode=${mode}&minutes=15`, 30000)
  const d = data?.data

  const stats = [
    { label: 'Rozważone', value: d?.considered ?? '—', color: 'text-slate-300' },
    { label: 'Odrzucone', value: d?.rejected ?? '—', color: 'text-amber-400' },
    { label: 'Kupione', value: d?.bought ?? '—', color: 'text-rldc-green-primary' },
    { label: 'Zamknięte', value: d?.closed ?? '—', color: 'text-sky-400' },
  ]

  const actions: any[] = d?.last_actions ?? []

  return (
    <div className="col-span-12 terminal-card border border-rldc-dark-border rounded-lg p-4 neon-card">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">
          Aktywność bota — ostatnie 15 min
        </div>
        {loading && <div className="text-[10px] text-slate-500 animate-pulse">Ładowanie…</div>}
        {d?.timestamp && (
          <div className="text-[10px] text-slate-600 font-mono">
            {new Date(d.timestamp).toLocaleTimeString('pl-PL')}
          </div>
        )}
      </div>
      <div className="flex gap-4 mb-3">
        {stats.map((s) => (
          <div key={s.label} className="flex-1 text-center rounded bg-rldc-dark-bg border border-rldc-dark-border px-2 py-2">
            <div className={`text-xl font-mono font-bold ${s.color}`}>{s.value}</div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mt-0.5">{s.label}</div>
          </div>
        ))}
      </div>
      {actions.length > 0 ? (
        <div className="space-y-1">
          {actions.map((a, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px] text-slate-300 leading-snug">
              <span className="font-mono text-slate-500 w-[60px] shrink-0">
                {a.ts ? new Date(a.ts).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }) : '—'}
              </span>
              <span>{a.description}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-slate-600 italic">Brak akcji w tym oknie</div>
      )}
    </div>
  )
}

// ─── Otwarte pozycje demo — wynik teraz ──────────────────────────────────────
function LivePositionsBlock({
  mode,
  onClose,
  onCloseQty,
}: {
  mode: string
  onClose?: (id: number) => void
  onCloseQty?: (id: number, qty: number) => void
}) {
  const { data: actData } = useFetch<any>(`/api/account/bot-activity?mode=${mode}&minutes=60`, 30000)
  const { data: posData } = useFetch<any>(`/api/positions?mode=${mode}`, 30000)
  const positions: any[] = posData?.data ?? []
  const enriched: any[] = actData?.data?.open_positions ?? []

  const enrichMap: Record<string, any> = {}
  enriched.forEach((e) => { enrichMap[e.symbol] = e })

  if (!positions.length) {
    return (
      <div className="terminal-card border border-rldc-dark-border rounded-lg p-4 neon-card">
        <div className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">Otwarte pozycje — wynik teraz</div>
        <div className="text-sm text-slate-600 italic">Brak otwartych pozycji</div>
      </div>
    )
  }

  return (
    <div className="terminal-card border border-rldc-dark-border rounded-lg p-4 neon-card">
      <div className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
        Otwarte pozycje — wynik teraz
      </div>
      <div className="space-y-3">
        {positions.map((p: any) => {
          const e = enrichMap[p.symbol] ?? {}
          const entry = p.entry_price ?? e.entry_price ?? 0
          const curr = p.current_price ?? e.current_price ?? 0
          const pnlEur = p.unrealized_pnl ?? e.pnl_eur ?? 0
          const pnlPct = entry > 0 ? ((curr - entry) / entry * 100) : (e.pnl_pct ?? 0)
          const tp = p.planned_tp ?? e.planned_tp
          const sl = p.planned_sl ?? e.planned_sl
          const holdReason = e.hold_reason ?? (tp ? `TP: ${Number(tp).toFixed(2)}` : '—')
          const isGain = pnlEur >= 0
          const qty = p.quantity ?? e.quantity ?? 0
          const q25 = qty * 0.25
          const q50 = qty * 0.5
          return (
            <div key={p.id ?? p.symbol} className="rounded-lg border border-rldc-dark-border bg-rldc-dark-bg px-3 py-3">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-sm text-slate-100">{p.symbol}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                    {p.side ?? e.side ?? 'LONG'}
                  </span>
                  <span className="text-[10px] text-slate-500">{Number(qty).toFixed(6)} szt.</span>
                </div>
                <div className={`text-sm font-mono font-bold ${isGain ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>
                  {isGain ? '+' : ''}{Number(pnlEur).toFixed(3)} EUR
                  <span className="ml-1 text-[10px]">({isGain ? '+' : ''}{pnlPct.toFixed(2)}%)</span>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-x-4 text-[11px] text-slate-400 mb-2">
                <div>Wejście: <span className="font-mono text-slate-200">{Number(entry).toFixed(2)}</span></div>
                <div>Teraz: <span className="font-mono text-slate-200">{Number(curr).toFixed(2)}</span></div>
                {tp && <div>TP: <span className="font-mono text-rldc-green-primary">{Number(tp).toFixed(2)}</span></div>}
                {sl && <div>SL: <span className="font-mono text-rldc-red-primary">{Number(sl).toFixed(2)}</span></div>}
              </div>
              <div className="flex items-center justify-between">
                <div className="text-[10px] text-slate-500 italic">{holdReason}</div>
                {onCloseQty && onClose && (
                  <div className="flex gap-1">
                    <button
                      onClick={() => onCloseQty(Number(p.id), q25)}
                      className="px-2 py-0.5 text-[10px] rounded bg-rldc-red-primary/10 text-rldc-red-primary hover:bg-rldc-red-primary hover:text-white transition border border-rldc-red-primary/20"
                    >25%</button>
                    <button
                      onClick={() => onCloseQty(Number(p.id), q50)}
                      className="px-2 py-0.5 text-[10px] rounded bg-rldc-red-primary/10 text-rldc-red-primary hover:bg-rldc-red-primary hover:text-white transition border border-rldc-red-primary/20"
                    >50%</button>
                    <button
                      onClick={() => onClose(Number(p.id))}
                      className="px-2 py-0.5 text-[10px] rounded bg-rldc-red-primary/20 text-rldc-red-primary hover:bg-rldc-red-primary hover:text-white transition"
                    >Zamknij</button>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function WlfiStatusCard() {
  const { data, loading } = useFetch<any>('/api/control/hold-status', 30000)
  const items: any[] = data?.data || []
  if (loading && !items.length) return null
  if (!items.length) return null
  return (
    <div className="col-span-12 flex flex-col gap-2">
      {items.map((item: any) => {
        const pct = item.progress_pct ?? 0
        const barColor = item.reached ? '#10b981' : pct >= 80 ? '#f59e0b' : '#0ea5e9'
        return (
          <div key={item.symbol} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-widest text-slate-400">HOLD:</span>
                <span className="text-sm font-bold text-slate-100">{item.symbol}</span>
                {item.reached && (
                  <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-rldc-green-primary/20 text-rldc-green-primary border border-rldc-green-primary/30">CEL OSIĄGNIĘTY</span>
                )}
              </div>
              <div className="text-right text-xs text-slate-400">
                {item.position_value != null ? (
                  <span className="font-mono text-slate-200">{item.position_value.toFixed(2)} EUR</span>
                ) : '--'} / <span className="font-mono text-slate-400">{item.target_eur} EUR</span>
              </div>
            </div>
            <div className="w-full h-2 rounded bg-rldc-dark-bg border border-rldc-dark-border overflow-hidden">
              <div
                className="h-full rounded transition-all duration-700"
                style={{ width: `${Math.min(100, pct)}%`, background: barColor }}
              />
            </div>
            <div className="flex items-center justify-between mt-1 text-[10px] text-slate-500">
              <span>{item.quantity != null ? `${item.quantity.toLocaleString('pl-PL')} szt.` : ''}</span>
              <span>{item.current_price != null ? `Cena: ${item.current_price.toFixed(5)} EUR` : ''}</span>
              <span className="font-mono" style={{ color: barColor }}>{pct.toFixed(1)}%</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function DashboardV2View({ tradingMode, onSymbolClick }: { tradingMode: 'live' | 'demo'; onSymbolClick?: (s: string) => void }) {
  const mode = tradingMode === 'live' ? 'live' : 'demo'
  const { data: summary } = useFetch<any>(`/api/portfolio/wealth?mode=${mode}`, 15000)
  const { data: economics } = useFetch<any>(`/api/account/analytics/overview?mode=${mode}`, 30000)
  const { data: control } = useFetch<any>(`/api/control/state`, 15000)
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCEUR')

  useEffect(() => {
    const wl = control?.data?.watchlist
    if (!Array.isArray(wl) || !wl.length) return
    if (!selectedSymbol) {
      setSelectedSymbol(String(wl[0]))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [control?.data?.watchlist])

  const quoteCcy = 'EUR'
  const equity = toNum(summary?.total_equity)
  const cash = toNum(summary?.free_cash ?? summary?.balance)
  const positionsValue = toNum(summary?.positions_value)
  const unrealized = toNum(summary?.unrealized_pnl)
  const realized24h = toNum(summary?.equity_change)
  const roiPct = toNum(summary?.equity_change_pct)
  const eco = economics?.data || {}
  const retentionRatio = toNum(eco.gross_to_net_retention_ratio) ?? 0
  const leakageRatio = toNum(eco.cost_leakage_ratio) ?? 0
  const overtradingScore = toNum(eco.overtrading_score) ?? 0

  const tradingEnabled = control?.data?.live_trading_enabled ?? control?.data?.demo_trading_enabled
  const tradingPill = (
    <div
      className={`px-3 py-1 rounded text-[11px] font-semibold border ${
        tradingEnabled === true
          ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
          : tradingEnabled === false
            ? 'bg-rldc-red-primary/15 text-rldc-red-primary border-rldc-red-primary/20'
            : 'bg-slate-500/10 text-slate-300 border-rldc-dark-border'
      }`}
    >
      LIVE TRADING: {tradingEnabled === null || tradingEnabled === undefined ? '--' : tradingEnabled ? 'WŁĄCZONY' : 'WYŁĄCZONY'}
    </div>
  )

  const closePosition = async (positionId: number) => {
    return closePositionQty(positionId, null)
  }

  const closePositionQty = async (positionId: number, quantity: number | null) => {
    try {
      const url = new URL(`${getApiBase()}/api/positions/${positionId}/close`)
      url.searchParams.set('mode', 'live')
      if (typeof quantity === 'number' && Number.isFinite(quantity) && quantity > 0) {
        url.searchParams.set('quantity', String(quantity))
      }
      const res = await fetch(url.toString(), { method: 'POST', headers: withAdminToken() })
      if (!res.ok) throw new Error('Błąd zamknięcia')
    } catch {
      // cicho — LivePositionsBlock odświeży się sam
    }
  }

  const kpis = [
    { label: 'Wartość konta', value: formatMoney(quoteCcy, equity), accent: 'text-rldc-green-primary' },
    { label: 'Wolne środki', value: formatMoney(quoteCcy, cash), accent: 'text-slate-100' },
    { label: 'Wartość pozycji', value: formatMoney(quoteCcy, positionsValue), accent: 'text-slate-100' },
    { label: 'Wynik na pozycjach', value: formatMoney(quoteCcy, unrealized), accent: unrealized && unrealized < 0 ? 'text-rldc-red-primary' : 'text-rldc-green-primary' },
    { label: 'Zmiana equity (24h)', value: formatMoney(quoteCcy, realized24h), accent: realized24h && realized24h < 0 ? 'text-rldc-red-primary' : 'text-rldc-green-primary' },
    { label: 'Zmiana equity % (24h)', value: formatPct(roiPct), accent: roiPct && roiPct < 0 ? 'text-rldc-red-primary' : 'text-rldc-green-primary' },
  ]

  const economicsKpis = [
    {
      label: 'Retencja brutto→netto',
      value: `${(retentionRatio * 100).toFixed(1)}%`,
      accent: retentionRatio >= 0.7 ? 'text-rldc-green-primary' : 'text-amber-400',
    },
    {
      label: 'Leakage kosztowe',
      value: `${(leakageRatio * 100).toFixed(1)}%`,
      accent: leakageRatio <= 0.3 ? 'text-rldc-green-primary' : 'text-rldc-red-primary',
    },
    {
      label: 'Overtrading score',
      value: `${(overtradingScore * 100).toFixed(1)}%`,
      accent: overtradingScore <= 0.35 ? 'text-rldc-green-primary' : 'text-rldc-red-primary',
    },
  ]

  return (
    <div className="flex-1 overflow-auto">
      <div className="p-6 max-w-[1680px] mx-auto">
        <div className="flex items-center justify-between">
          <DashboardHeader title="RLDC Ain Alyzer" tradingMode={tradingMode} />
          {tradingPill}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
          {kpis.map((k) => (
            <div key={k.label} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">{k.label}</div>
              <div className={`text-lg font-semibold font-mono ${k.accent}`}>{k.value}</div>
              <div className="text-[10px] text-slate-500 mt-1">{quoteCcy || '--'}</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          {economicsKpis.map((k) => (
            <div key={k.label} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">{k.label}</div>
              <div className={`text-lg font-semibold font-mono ${k.accent}`}>{k.value}</div>
              <div className="text-[10px] text-slate-500 mt-1">KONTROLA KOSZTÓW</div>
            </div>
          ))}
        </div>

	        <div className="grid grid-cols-12 gap-4">
	          <WlfiStatusCard />
	          <BotActivityBlock mode={mode} />
	          <div className="col-span-12 lg:col-span-8 space-y-4">
	            <TradingView
	              symbol={selectedSymbol}
	              onSymbolChange={(s) => setSelectedSymbol(s)}
	              allowSymbolSelect={true}
	              refreshMs={60000}
	              titleOverride="Wykres rynku"
	            />
	            <EquityCurve mode={mode} hours={24} quoteCcy={quoteCcy || undefined} refreshMs={60000} />
	            <div className="grid grid-cols-12 gap-4">
	              <div className="col-span-12 xl:col-span-7">
	                <OpenOrders mode={mode} />
	              </div>
              <div className="col-span-12 xl:col-span-5">
                <LivePositionsBlock
                  mode={mode}
                  onClose={(id) => closePosition(id)}
                  onCloseQty={(id, qty) => closePositionQty(id, qty)}
                />
              </div>
            </div>
	            <OpenAIRangesWidget />
	          </div>
	          <div className="col-span-12 lg:col-span-4 space-y-4">
	            <DecisionsRiskPanel mode={mode} symbol={selectedSymbol} />
	            <MarketInsights />
	          </div>
	        </div>
      </div>
    </div>
  )
}

function ClassicDashboardView({ tradingMode }: { tradingMode: 'live' | 'demo' }) {
  const mode = tradingMode === 'live' ? 'live' : 'demo'
  const { data: openaiStatus } = useFetch<any>(`/api/account/openai-status`, 60000)
  return (
    <div className="flex-1 overflow-auto">
      <div className="p-6 max-w-[1680px] mx-auto">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-bold terminal-title">RLDC Ain Alyzer (Classic)</h1>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-3 py-1 bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded text-sm font-bold">
              <span className="inline-block w-2 h-2 bg-amber-400 rounded-full animate-pulse"></span>
              LIVE — Binance
            </div>
            <OpenAIStatusPill status={openaiStatus?.data} />
          </div>
        </div>

        <ActionBanner />
        <KpiStrip tradingMode={tradingMode} />

        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 lg:col-span-6">
            <TradingView symbol="WLFI/EUR" allowSymbolSelect={false} titleOverride="WLFI/EUR" refreshMs={60000} />
          </div>
          <div className="col-span-12 lg:col-span-6">
            <TradingView symbol="BTC/EUR" allowSymbolSelect={false} titleOverride="BTC/EUR" refreshMs={60000} />
          </div>

          <div className="col-span-12">
            <TradingView allowSymbolSelect={true} refreshMs={60000} titleOverride="Wykres (wybierz parę)" />
          </div>

          <div className="col-span-12 lg:col-span-8">
            <OpenAIRangesWidget />
          </div>
          <div className="col-span-12 lg:col-span-4 space-y-4">
            <DecisionRisk mode={mode} />
            <PendingOrdersWidget mode={tradingMode === 'live' ? 'live' : 'demo'} />
            <MarketInsights />
          </div>

          <div className="col-span-12 lg:col-span-7">
            <OpenOrders mode={tradingMode === 'live' ? 'live' : 'demo'} />
          </div>
          <div className="col-span-12 lg:col-span-5">
            <DecisionReasonsWidget mode={tradingMode === 'live' ? 'live' : 'demo'} />
          </div>
        </div>
      </div>
    </div>
  )
}

function OpenAIStatusPill({ status }: { status: any }) {
  const s = status?.status as string | undefined
  if (!s) {
    return (
      <div className="px-3 py-1 bg-slate-500/15 text-slate-300 rounded text-sm font-medium">
        OpenAI: --
      </div>
    )
  }
  if (s === 'ok') {
    return (
      <div className="px-3 py-1 bg-rldc-green-primary/15 text-rldc-green-primary rounded text-sm font-medium">
        OpenAI: OK
      </div>
    )
  }
  const code = status?.code ? String(status.code) : 'error'
  return (
    <div className="px-3 py-1 bg-rldc-red-primary/15 text-rldc-red-primary rounded text-sm font-medium">
      OpenAI: {code}
    </div>
  )
}

function ActionBanner() {
  const { data } = useFetch<any>(`/api/market/ranges`, 60000)
  const focus = new Set(['WLFIEUR', 'BTCEUR'])
  const items = (data?.data || []).filter((r: any) => focus.has(r.symbol)).map((r: any) => {
    let action = 'CZEKAJ'
    if (r.buy_action && String(r.buy_action).includes('KUP')) action = 'KUP'
    if (r.sell_action && String(r.sell_action).includes('SPRZEDAJ')) action = 'SPRZEDAJ'
    return { symbol: r.symbol, action }
  })
  if (!items.length) return null
  return (
    <div className="mb-4 terminal-card p-4">
      <div className="text-xs terminal-muted mb-2">Co robić teraz (prosto):</div>
      <div className="flex flex-wrap gap-3">
        {items.map((i: any) => (
          <div key={i.symbol} className="px-3 py-2 bg-rldc-dark-bg border border-rldc-dark-border rounded text-sm">
            {i.symbol}: <span className="font-semibold text-slate-200">{i.action}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function OpenAIRangesWidget() {
  const { data, loading, error } = useFetch<any>(`/api/market/ranges`, 60000)
  const { data: openaiStatus } = useFetch<any>(`/api/account/openai-status`, 60000)
  const { data: lastAnalysisErr } = useFetch<any>(
    `/api/account/system-logs?limit=1&module=analysis&level=ERROR`,
    60000
  )
  const rows = (data?.data || []).map((r: any) => {
    return [
      r.symbol,
      r.buy_action || 'CZEKAJ',
      r.buy_target || '--',
      r.sell_action || 'CZEKAJ',
      r.sell_target || '--',
      r.comment || 'Zakresy wyliczone automatycznie',
      r.timestamp || '--',
    ]
  })
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
      <h2 className="text-lg font-semibold mb-4 text-slate-200">AI — sugestie kupna i sprzedaży</h2>
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      {!loading && !error && rows.length === 0 && (
        <div className="text-sm text-slate-400 mb-4">
          Brak zakresów. Sprawdź OPENAI_API_KEY w `.env` i odśwież po min. 1 cyklu analizy.
          {openaiStatus?.data?.status === 'error' && (
            <div className="mt-2 text-xs text-rldc-red-primary">
              OpenAI: {String(openaiStatus.data.code || 'error')} ({String(openaiStatus.data.http_status || '--')}) —{' '}
              {String(openaiStatus.data.message || '').slice(0, 180)}
            </div>
          )}
          {lastAnalysisErr?.data?.[0]?.message && (
            <div className="mt-2 text-xs text-slate-500">
              Ostatni błąd OpenAI: {String(lastAnalysisErr.data[0].message).slice(0, 180)}
            </div>
          )}
        </div>
      )}
      <SimpleTable
        title="Sugestie kupna/sprzedaży"
        headers={['Symbol', 'Decyzja: Kup', 'Cel kupna (EUR)', 'Decyzja: Sprzedaj', 'Cel sprzedaży (EUR)', 'Komentarz', 'Czas']}
        rows={rows}
      />
    </div>
  )
}

function DecisionReasonsWidget({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading, error } = useFetch<any>(`/api/orders?mode=${mode}&limit=20`, 60000)
  const rows = (data?.data || []).map((o: any) => [
    o.symbol,
    o.side,
    o.timestamp,
    o.reason || '--',
  ])
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card mt-4">
      <h2 className="text-lg font-semibold mb-4 text-slate-200">Ostatnie decyzje (powód zlecenia)</h2>
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <SimpleTable
        title="Uzasadnienia decyzji"
        headers={['Symbol', 'Kierunek', 'Czas', 'Powód']}
        rows={rows}
      />
    </div>
  )
}

function PendingOrdersWidget({ mode }: { mode: 'demo' | 'live' }) {
  const [refreshKey, setRefreshKey] = useState(0)
  const [actionStatus, setActionStatus] = useState<string | null>(null)
  const { data, loading, error } = useFetch<any>(`/api/orders/pending?mode=${mode}&limit=50&rk=${refreshKey}`, 60000)
  const items = data?.data || []

  const act = async (id: number, action: 'confirm' | 'reject') => {
    setActionStatus(`${action === 'confirm' ? 'Potwierdzam' : 'Odrzucam'} #${id}...`)
    try {
      const headers: Record<string, string> = withAdminToken()
      const res = await fetch(`${getApiBase()}/api/orders/pending/${id}/${action}`, { method: 'POST', headers })
      if (!res.ok) throw new Error('Błąd akcji')
      setRefreshKey((k) => k + 1)
      setActionStatus('OK')
    } catch {
      setActionStatus('Akcja nieudana (sprawdź ADMIN_TOKEN)')
    }
  }

  const rows = items.map((p: any) => {
    const canAct = String(p.status || '').toUpperCase() === 'PENDING'
    return [
      p.id,
      p.symbol,
      p.side,
      p.quantity,
      p.price ?? '--',
      p.status,
      p.created_at || '--',
      canAct ? (
        <div className="flex items-center gap-2">
          <button
            onClick={() => act(Number(p.id), 'confirm')}
            className="px-2 py-1 text-[10px] rounded bg-rldc-green-primary/20 text-rldc-green-primary hover:bg-rldc-green-primary/30 transition"
          >
            Potwierdź
          </button>
          <button
            onClick={() => act(Number(p.id), 'reject')}
            className="px-2 py-1 text-[10px] rounded bg-rldc-red-primary/20 text-rldc-red-primary hover:bg-rldc-red-primary/30 transition"
          >
            Odrzuć
          </button>
        </div>
      ) : (
        '--'
      ),
    ]
  })
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card mt-4">
      <h2 className="text-lg font-semibold mb-4 text-slate-200">Oczekujące zlecenia (Telegram)</h2>
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      {actionStatus && <div className="text-xs text-slate-500 mb-3">{actionStatus}</div>}
      <SimpleTable
        title="Zlecenia oczekujące na potwierdzenie"
        headers={['ID', 'Symbol', 'Kierunek', 'Ilość', 'Cena', 'Status', 'Czas', 'Akcje']}
        rows={rows}
      />
    </div>
  )
}

function KpiStrip({ tradingMode }: { tradingMode: 'live' | 'demo' }) {
  const mode = tradingMode === 'live' ? 'live' : 'demo'
  const { data } = useFetch<any>(`/api/portfolio/wealth?mode=${mode}`, 60000)
  const { data: risk } = useFetch<any>(`/api/account/risk?mode=${mode}`, 60000)
  const kpi = data || {}
  const riskData = risk?.data || {}
  const items = [
    { label: 'Wartość konta', value: kpi.total_equity != null ? `EUR ${Number(kpi.total_equity).toFixed(2)}` : '--' },
    { label: 'Wolne środki', value: kpi.free_cash != null ? `EUR ${Number(kpi.free_cash).toFixed(2)}` : '--' },
    { label: 'Wynik na pozycjach', value: kpi.total_pnl != null ? `EUR ${Number(kpi.total_pnl).toFixed(2)}` : '--' },
    { label: 'Poziom zabezpieczenia', value: kpi.margin_level ? `${Number(kpi.margin_level).toFixed(2)}%` : '--' },
    { label: 'Limit straty dziennej', value: riskData.daily_loss_limit ? `${riskData.daily_loss_limit}` : '--' },
    { label: 'Maks. obsunięcie wartości', value: riskData.worst_drawdown_pct ? `${riskData.worst_drawdown_pct}%` : '--' },
  ]
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
      {items.map((item) => (
        <div
          key={item.label}
          className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card"
        >
          <div className="text-[10px] uppercase tracking-widest text-slate-500">{item.label}</div>
          <div className="text-lg font-semibold text-slate-100 font-mono">{item.value}</div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Widok diagnostyczny: Dlaczego bot demo nie wszedł w pozycję?
// ---------------------------------------------------------------------------
interface TraceSymbol {
  symbol: string
  reason_code: string
  reason_pl: string
  trace_age_seconds: number | null
  has_position: boolean
  has_pending: boolean
  pending_status: string | null
  signal_type: string | null
  signal_confidence: number | null
  signal_age_seconds: number | null
  details: Record<string, any>
}

interface TraceSummary {
  executed: number
  pending: number
  blocked: number
  no_signal: number
}

interface ExecutionTraceData {
  success: boolean
  mode: string
  window_minutes: number
  symbols: TraceSymbol[]
  summary: TraceSummary
  updated_at: string
}

function reasonBadge(code: string) {
  if (code.startsWith('all_gates') || code.includes('execution')) return 'bg-emerald-900/40 text-emerald-300 border-emerald-700'
  if (code.includes('cooldown') || code.includes('pending') || code.includes('old') || code.includes('hold_mode')) return 'bg-amber-900/30 text-amber-300 border-amber-700'
  return 'bg-red-900/30 text-red-300 border-red-700'
}

function traceAge(s: number | null): string {
  if (s == null) return '—'
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}min`
  return `${Math.floor(s / 3600)}h`
}

function ExecutionTraceView({ mode }: { mode: string }) {
  const { data, loading, error, lastUpdated } = useFetch<ExecutionTraceData>(
    `/api/signals/execution-trace?mode=${mode}&limit_minutes=30`, 30000
  )

  const [filterError, setFilterError] = useState(false)

  const symbols = data?.symbols ?? []
  const summary = data?.summary

  const filtered = filterError
    ? symbols.filter(s => !s.reason_code.includes('all_gates') && !s.reason_code.includes('execution') && s.reason_code !== 'no_trace')
    : symbols

  return (
    <div className="flex-1 p-4 lg:p-6 overflow-y-auto">
      <ViewHeader
        title="Diagnostyka — Dlaczego bot nie wszedł?"
        description={`Podgląd ostatnich 30 minut decyzji bota ${mode.toUpperCase()}. Każdy symbol ma opis przyczyny blokady lub potwierdzenia wejścia.`}
      />
      <DataStatus loading={loading} error={error} lastUpdated={lastUpdated} refreshMs={30000} />

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          {[
            { label: 'Wykonano', value: summary.executed, color: 'text-emerald-400' },
            { label: 'Oczekuje', value: summary.pending, color: 'text-amber-400' },
            { label: 'Zablokowano', value: summary.blocked, color: 'text-red-400' },
            { label: 'Brak sygnału', value: summary.no_signal, color: 'text-slate-400' },
          ].map(({ label, value, color }) => (
            <div key={label} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
              <div className={`text-2xl font-bold font-mono ${color}`}>{value}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={() => setFilterError(!filterError)}
          className={`px-3 py-1.5 rounded text-xs font-semibold border transition-colors ${filterError ? 'bg-red-900/40 text-red-300 border-red-700' : 'bg-slate-800 text-slate-400 border-slate-700 hover:border-slate-500'}`}
        >
          {filterError ? '✕ Tylko problemy' : 'Pokaż tylko problemy'}
        </button>
        <span className="text-xs text-slate-500">{filtered.length} symboli</span>
      </div>

      {loading && symbols.length === 0 && (
        <div className="text-slate-400 text-sm text-center py-8">Ładowanie danych diagnostycznych…</div>
      )}

      <div className="space-y-2">
        {filtered.map((row) => {
          const badgeCls = reasonBadge(row.reason_code)
          const confPct = row.signal_confidence != null ? Math.round(row.signal_confidence * 100) : null
          return (
            <div
              key={row.symbol}
              className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card hover:border-slate-500 transition-colors"
            >
              <div className="flex items-start gap-3 flex-wrap">
                <div className="font-mono text-sm font-bold text-slate-200 w-28 shrink-0">{row.symbol}</div>
                <div className={`text-xs px-2 py-0.5 rounded border font-medium leading-5 ${badgeCls}`}>
                  {row.reason_pl}
                </div>
                <div className="ml-auto flex items-center gap-3 text-xs text-slate-500 flex-wrap">
                  {row.has_position && <span className="text-amber-400">📊 Otwarta pozycja</span>}
                  {row.has_pending && <span className="text-amber-300">⏳ {row.pending_status}</span>}
                  {confPct != null && (
                    <span className={confPct >= 70 ? 'text-emerald-400' : confPct >= 55 ? 'text-amber-300' : 'text-red-400'}>
                      Pewność: {confPct}%
                    </span>
                  )}
                  {row.signal_type && <span className="text-slate-400">Sygnał: {row.signal_type}</span>}
                  {row.trace_age_seconds != null && <span title="Wiek ostatniej decyzji">⏱ {traceAge(row.trace_age_seconds)}</span>}
                </div>
              </div>
              {/* Szczegóły techniczne (rozwijalne) */}
              {Object.keys(row.details).length > 0 && (
                <details className="mt-2">
                  <summary className="text-xs text-slate-600 cursor-pointer hover:text-slate-400 select-none">Szczegóły techniczne</summary>
                  <pre className="mt-1 text-[10px] text-slate-500 bg-slate-900/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                    {JSON.stringify(row.details, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )
        })}
      </div>

      {!loading && filtered.length === 0 && (
        <div className="text-slate-500 text-sm text-center py-10">
          {filterError ? 'Brak zablokowanych symboli — wszystko OK 🎉' : 'Brak danych diagnostycznych w tym oknie czasowym.'}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// TELEGRAM INTELLIGENCE VIEW
// ─────────────────────────────────────────────────────────────────────────────

function TelegramIntelligenceView({ mode }: { mode: 'demo' | 'live' }) {
  const { data: stateData, loading: stateLoading } = useFetch<any>(`/api/telegram-intel/state?mode=${mode}`, 15000)
  const { data: msgsData, loading: msgsLoading } = useFetch<any>(`/api/telegram-intel/messages?limit=30&since_minutes=120`, 20000)

  const [goalForm, setGoalForm] = useState({
    target_type: 'position_value',
    current_value: '',
    target_value: '',
    symbol: '',
  })
  const [goalResult, setGoalResult] = useState<any>(null)
  const [goalLoading, setGoalLoading] = useState(false)

  const state = stateData?.data
  const msgs: any[] = msgsData?.messages || []

  const evaluateGoal = async () => {
    if (!goalForm.current_value || !goalForm.target_value) return
    setGoalLoading(true)
    try {
      const resp = await fetch(`${getApiBase()}/api/telegram-intel/evaluate-goal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_type: goalForm.target_type,
          current_value: parseFloat(goalForm.current_value),
          target_value: parseFloat(goalForm.target_value),
          symbol: goalForm.symbol || undefined,
        }),
      })
      const j = await resp.json()
      setGoalResult(j.result)
    } catch (e) {
      setGoalResult({ realism: 'błąd', explanation_pl: 'Błąd połączenia z API' })
    } finally {
      setGoalLoading(false)
    }
  }

  const biasColor = (bias: string) => {
    if (bias?.includes('BUY')) return 'text-green-400'
    if (bias?.includes('SELL')) return 'text-red-400'
    if (bias?.includes('NO_TRADING')) return 'text-red-600'
    return 'text-amber-400'
  }

  const categoryLabel = (cat: string) => {
    const m: Record<string, string> = {
      SIGNAL_MESSAGE: 'Sygnał',
      EXECUTION_MESSAGE: 'Egzekucja',
      BLOCKER_MESSAGE: 'Bloker',
      RISK_MESSAGE: 'Ryzyko',
      SYSTEM_STATUS_MESSAGE: 'Status',
      OPERATOR_MESSAGE: 'Operator',
      TARGET_MESSAGE: 'Cel',
      UNKNOWN: 'Inne',
    }
    return m[cat] || cat
  }

  const categoryBadge = (cat: string) => {
    const cls: Record<string, string> = {
      SIGNAL_MESSAGE: 'bg-teal-900/40 text-teal-300 border-teal-700/40',
      EXECUTION_MESSAGE: 'bg-green-900/40 text-green-300 border-green-700/40',
      BLOCKER_MESSAGE: 'bg-orange-900/40 text-orange-300 border-orange-700/40',
      RISK_MESSAGE: 'bg-red-900/40 text-red-300 border-red-700/40',
      SYSTEM_STATUS_MESSAGE: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/40',
      OPERATOR_MESSAGE: 'bg-blue-900/40 text-blue-300 border-blue-700/40',
      TARGET_MESSAGE: 'bg-purple-900/40 text-purple-300 border-purple-700/40',
      UNKNOWN: 'bg-slate-800/40 text-slate-400 border-slate-700/40',
    }
    return cls[cat] || 'bg-slate-800/40 text-slate-400 border-slate-700/40'
  }

  const realismColor = (r: string) => {
    if (r === 'bardzo_realny') return 'text-green-400'
    if (r === 'realny') return 'text-teal-400'
    if (r === 'możliwy') return 'text-yellow-400'
    if (r === 'trudny') return 'text-orange-400'
    return 'text-red-400'
  }

  return (
    <div className="flex-1 p-4 space-y-4 max-w-6xl mx-auto">
      <ViewHeader
        title="Telegram AI — Interpretacja"
        description="Warstwa interpretacyjna Telegrama: klasyfikacja wiadomości, analiza blokerów, ocena celu."
      />

      {/* SEKCJA 1: Stan aktualny */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Bias i pilność */}
        <div className="terminal-card border border-rldc-dark-border rounded-lg p-4">
          <div className="text-[10px] uppercase text-slate-500 tracking-widest mb-3">Co wynika z Telegrama?</div>
          {stateLoading ? (
            <div className="text-slate-500 text-sm">Ładowanie...</div>
          ) : state ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-slate-500">Bias:</span>
                <span className={`text-sm font-bold ${biasColor(state.decision_bias)}`}>
                  {state.decision_bias || 'NEUTRAL'}
                </span>
              </div>
              {state.decision_bias_reason && (
                <div className="text-[11px] text-slate-400 border-l border-slate-700 pl-2">
                  {state.decision_bias_reason}
                </div>
              )}
              <div className="flex items-center gap-2 pt-1">
                <span className="text-[10px] text-slate-500">Pilność:</span>
                <div className="flex-1 bg-slate-800 rounded-full h-2">
                  <div
                    className="h-2 rounded-full bg-gradient-to-r from-teal-600 to-red-500 transition-all"
                    style={{ width: `${Math.round((state.urgency_score || 0) * 100)}%` }}
                  />
                </div>
                <span className="text-[10px] text-slate-400">{Math.round((state.urgency_score || 0) * 100)}%</span>
              </div>
              {state.main_problem && (
                <div className="mt-2 p-2 bg-red-900/20 border border-red-800/30 rounded text-[11px] text-red-300">
                  ⚠ Główny problem: {state.main_problem}
                </div>
              )}
              {state.main_opportunity && (
                <div className="mt-1 p-2 bg-teal-900/20 border border-teal-800/30 rounded text-[11px] text-teal-300">
                  ✦ Okazja: {state.main_opportunity}
                </div>
              )}
            </div>
          ) : (
            <div className="text-slate-500 text-sm">Brak danych</div>
          )}
        </div>

        {/* Ostatnie zdarzenia */}
        <div className="terminal-card border border-rldc-dark-border rounded-lg p-4">
          <div className="text-[10px] uppercase text-slate-500 tracking-widest mb-3">Ostatnie zdarzenia</div>
          {state ? (
            <div className="space-y-2 text-[11px]">
              {state.last_signal && (
                <div className="p-2 bg-teal-900/15 border border-teal-800/30 rounded">
                  <span className="text-teal-400 font-bold">Sygnał: </span>
                  <span className="text-slate-300">{state.last_signal.symbol} {state.last_signal.side}</span>
                  {state.last_signal.confidence && (
                    <span className="text-slate-400"> ({Math.round(state.last_signal.confidence * 100)}%)</span>
                  )}
                  <span className="text-slate-500 ml-1">— {state.last_signal.age_minutes} min temu</span>
                </div>
              )}
              {state.last_execution && (
                <div className="p-2 bg-green-900/15 border border-green-800/30 rounded">
                  <span className="text-green-400 font-bold">Egzekucja: </span>
                  <span className="text-slate-300">{state.last_execution.symbol} {state.last_execution.exec_code || state.last_execution.side}</span>
                  <span className="text-slate-500 ml-1">— {state.last_execution.age_minutes} min temu</span>
                </div>
              )}
              {Array.isArray(state.last_blockers) && state.last_blockers.length > 0 && (
                <div className="p-2 bg-orange-900/15 border border-orange-800/30 rounded">
                  <span className="text-orange-400 font-bold">Blokery (15 min): </span>
                  {state.last_blockers.slice(0, 2).map((b: any, i: number) => (
                    <span key={i} className="text-slate-300">
                      {b.label} ({b.count}×){i < Math.min(state.last_blockers.length, 2) - 1 ? ', ' : ''}
                    </span>
                  ))}
                </div>
              )}
              {(!state.last_signal && !state.last_execution && (!state.last_blockers || state.last_blockers.length === 0)) && (
                <div className="text-slate-500">Brak aktywnych zdarzeń w ostatnich 2 godzinach.</div>
              )}
            </div>
          ) : (
            <div className="text-slate-500 text-sm">Ładowanie...</div>
          )}
        </div>
      </div>

      {/* SEKCJA 2: Statystyki 2h */}
      {state?.stats && (
        <div className="terminal-card border border-rldc-dark-border rounded-lg p-4">
          <div className="text-[10px] uppercase text-slate-500 tracking-widest mb-3">Statystyki ostatnich 2 godzin</div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              { label: 'Sygnały', value: state.stats.signals_2h, color: 'text-teal-300' },
              { label: 'Blokery (15 min)', value: state.stats.blockers_15m, color: 'text-orange-300' },
              { label: 'TP realizacje', value: state.stats.tp_fills_30m, color: 'text-green-300' },
              { label: 'SL hity', value: state.stats.sl_hits_30m, color: 'text-red-300' },
              { label: 'Akcje operatora', value: state.stats.operator_actions_2h, color: 'text-blue-300' },
            ].map((s, i) => (
              <div key={i} className="bg-rldc-dark-card rounded p-2 text-center border border-rldc-dark-border">
                <div className={`text-xl font-bold ${s.color}`}>{s.value ?? 0}</div>
                <div className="text-[9px] text-slate-500 mt-1">{s.label}</div>
              </div>
            ))}
          </div>
          {state.profit_pressure && (
            <div className="mt-3 text-[11px] text-slate-400 border-t border-rldc-dark-border pt-2 grid grid-cols-2 md:grid-cols-4 gap-2">
              <span><span className="text-slate-500">Status 24h:</span> <span className="text-slate-200">{state.profit_pressure.status}</span></span>
              <span><span className="text-slate-500">PnL 24h:</span> <span className={state.profit_pressure.net_pnl_24h >= 0 ? 'text-green-400' : 'text-red-400'}>{state.profit_pressure.net_pnl_24h?.toFixed(2)} EUR</span></span>
              <span><span className="text-slate-500">Otwarte pozycje:</span> <span className="text-slate-200">{state.profit_pressure.open_positions}</span></span>
              <span><span className="text-slate-500">Niezrealizowany PnL:</span> <span className={state.profit_pressure.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>{state.profit_pressure.unrealized_pnl?.toFixed(2)} EUR</span></span>
            </div>
          )}
        </div>
      )}

      {/* SEKCJA 3: Ocena celu */}
      <div className="terminal-card border border-amber-700/30 rounded-lg p-4">
        <div className="text-[10px] uppercase text-amber-500 tracking-widest mb-3">Ocena realności celu</div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
          <div>
            <label className="text-[10px] text-slate-500 block mb-1">Typ celu</label>
            <select
              title="Typ celu"
              value={goalForm.target_type}
              onChange={e => setGoalForm(f => ({ ...f, target_type: e.target.value }))}
              className="w-full bg-rldc-dark-card border border-rldc-dark-border rounded px-2 py-1 text-[11px] text-slate-200"
            >
              <option value="position_value">Wartość pozycji (EUR)</option>
              <option value="portfolio_value">Wartość portfela (EUR)</option>
              <option value="profit_pct">Zysk procentowy (%)</option>
              <option value="price_target">Cena docelowa</option>
            </select>
          </div>
          <div>
            <label className="text-[10px] text-slate-500 block mb-1">Aktualna wartość</label>
            <input
              type="number"
              placeholder="np. 500"
              value={goalForm.current_value}
              onChange={e => setGoalForm(f => ({ ...f, current_value: e.target.value }))}
              className="w-full bg-rldc-dark-card border border-rldc-dark-border rounded px-2 py-1 text-[11px] text-slate-200"
            />
          </div>
          <div>
            <label className="text-[10px] text-slate-500 block mb-1">Cel</label>
            <input
              type="number"
              placeholder="np. 650"
              value={goalForm.target_value}
              onChange={e => setGoalForm(f => ({ ...f, target_value: e.target.value }))}
              className="w-full bg-rldc-dark-card border border-rldc-dark-border rounded px-2 py-1 text-[11px] text-slate-200"
            />
          </div>
          <div>
            <label className="text-[10px] text-slate-500 block mb-1">Symbol (opcjonalnie)</label>
            <input
              type="text"
              placeholder="np. ETHEUR"
              value={goalForm.symbol}
              onChange={e => setGoalForm(f => ({ ...f, symbol: e.target.value.toUpperCase() }))}
              className="w-full bg-rldc-dark-card border border-rldc-dark-border rounded px-2 py-1 text-[11px] text-slate-200 uppercase"
            />
          </div>
        </div>
        <button
          onClick={evaluateGoal}
          disabled={goalLoading || !goalForm.current_value || !goalForm.target_value}
          className="px-4 py-1.5 bg-amber-700/30 hover:bg-amber-700/50 text-amber-300 text-[11px] font-bold rounded border border-amber-700/40 transition disabled:opacity-40"
        >
          {goalLoading ? 'Oceniam...' : 'Oceń cel'}
        </button>

        {goalResult && (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center gap-3 text-[11px]">
              <span className="text-slate-500">Ocena:</span>
              <span className={`font-bold text-sm ${realismColor(goalResult.realism)}`}>
                {goalResult.realism?.replace(/_/g, ' ')}
              </span>
              <span className="text-slate-500">|</span>
              <span className="text-slate-400">Wymagany ruch: {goalResult.required_move_pct?.toFixed(2)}%</span>
              {goalResult.required_price && (
                <>
                  <span className="text-slate-500">|</span>
                  <span className="text-slate-400">Cena docelowa: {goalResult.required_price}</span>
                </>
              )}
              <span className="text-slate-500">|</span>
              <span className="text-slate-400">Pewność: {Math.round((goalResult.confidence || 0) * 100)}%</span>
            </div>
            <div className="text-[11px] text-slate-300 bg-rldc-dark-card border border-rldc-dark-border rounded p-2">
              {goalResult.explanation_pl}
            </div>
            {goalResult.time_horizon_estimate && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(goalResult.time_horizon_estimate).map(([win, label]) => (
                  <div key={win} className="bg-rldc-dark-card border border-rldc-dark-border rounded p-2">
                    <div className="text-[9px] text-slate-500 uppercase">{win}</div>
                    <div className="text-[11px] text-slate-300 mt-1">{label as string}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* SEKCJA 4: Archiwum wiadomości */}
      <div className="terminal-card border border-rldc-dark-border rounded-lg p-4">
        <div className="text-[10px] uppercase text-slate-500 tracking-widest mb-3">
          Archiwum Telegram — ostatnie 2 godziny ({msgs.length})
        </div>
        {msgsLoading ? (
          <div className="text-slate-500 text-sm">Ładowanie...</div>
        ) : msgs.length === 0 ? (
          <div className="text-slate-500 text-sm">
            Brak wiadomości. Wiadomości będą pojawiać się po pierwszym wysłaniu powiadomienia przez bota lub kolektor.
          </div>
        ) : (
          <div className="space-y-1 max-h-80 overflow-y-auto pr-1">
            {msgs.map((m: any) => (
              <div
                key={m.id}
                className="flex items-start gap-2 text-[10px] hover:bg-slate-800/20 rounded px-1 py-0.5"
              >
                <span className="text-slate-600 whitespace-nowrap shrink-0">
                  {m.ts ? new Date(m.ts).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }) : ''}
                </span>
                <span className={`shrink-0 px-1 py-0.5 rounded border text-[9px] ${categoryBadge(m.category)}`}>
                  {categoryLabel(m.category)}
                </span>
                {m.symbol && (
                  <span className="shrink-0 text-teal-400 font-mono">{m.symbol}</span>
                )}
                {m.side && (
                  <span className={`shrink-0 font-bold ${m.side === 'BUY' ? 'text-green-400' : m.side === 'SELL' ? 'text-red-400' : 'text-amber-400'}`}>
                    {m.side}
                  </span>
                )}
                <span className="text-slate-400 truncate">{m.text}</span>
                {m.action_required && (
                  <span className="shrink-0 text-red-400 font-bold">!</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function OtherView({ activeView, tradingMode, onSymbolClick }: MainContentProps & { onSymbolClick?: (s: string) => void }) {
  const mode = tradingMode === 'live' ? 'live' : 'demo'

  if (activeView === 'execution-trace') {
    return <ExecutionTraceView mode={mode} />
  }
  if (activeView === 'operator-console') {
    return <DiagnosticHubView mode={mode} />
  }
  if (activeView === 'markets') {
    return <MarketsView onSymbolClick={onSymbolClick} />
  }
  if (activeView === 'telegram-intel') {
    return <TelegramIntelligenceView mode={mode} />
  }
  if (activeView === 'trade-desk') {
    return <TradeDeskView mode={mode} />
  }
  if (activeView === 'exit-diagnostics') {
    return <ExitDiagnosticsView mode={mode} />
  }
  if (activeView === 'portfolio') {
    return <PortfolioView mode={mode} onSymbolClick={onSymbolClick} />
  }
  if (activeView === 'strategies') {
    return <StrategiesView onSymbolClick={onSymbolClick} />
  }
  if (activeView === 'ai-signals') {
    return <SignalsView onSymbolClick={onSymbolClick} />
  }
  if (activeView === 'risk') {
    return <RiskView mode={mode} onSymbolClick={onSymbolClick} />
  }
  if (activeView === 'decisions') {
    return <DecisionsView mode={mode} />
  }
  if (activeView === 'position-analysis') {
    return <PositionAnalysisView mode={mode} onSymbolClick={onSymbolClick} />
  }
  if (activeView === 'backtest') {
    return <BacktestView mode={mode} />
  }
  if (activeView === 'economics' || activeView === 'alerts' || activeView === 'news') {
    return <MarketProxyView activeView={activeView} mode={mode} />
  }
  if (activeView === 'blog') {
    return <BlogView />
  }
  if (activeView === 'settings' || activeView === 'logs') {
    return <SettingsView activeView={activeView} mode={mode} />
  }
  if (activeView === 'macro-reports') {
    return <MacroReportsView mode={mode} />
  }
  if (activeView === 'reports') {
    return <ReportsView mode={mode} />
  }

  return (
    <div className="flex-1 p-6">
      <div className="bg-rldc-dark-card rounded-lg p-8 text-center border border-rldc-dark-border neon-card">
        <h2 className="text-2xl font-bold text-rldc-teal-primary mb-2">
          {activeView.charAt(0).toUpperCase() + activeView.slice(1)}
        </h2>
        <p className="text-slate-400">
          Brak danych dla tego widoku
        </p>
      </div>
    </div>
  )
}

function MarketsView({ onSymbolClick }: { onSymbolClick?: (s: string) => void }) {
  const { data, loading, error, lastUpdated } = useFetch<any>(`/api/market/summary`, 15000)
  const { data: rangesData } = useFetch<any>(`/api/market/ranges`)
  const { data: quantum } = useFetch<any>(`/api/market/quantum`)
  const rangesMap = new Map<string, any>((rangesData?.data || []).map((r: any) => [r.symbol, r]))
  const qMap = new Map<string, any>((quantum?.data || []).map((q: any) => [q.symbol, q]))
  const rows = (data?.data || []).map((m: any) => {
    const r: any = rangesMap.get(m.symbol)
    const q: any = qMap.get(m.symbol)
    const buyRange = r ? `${r.buy_low} - ${r.buy_high}` : '--'
    const sellRange = r ? `${r.sell_low} - ${r.sell_high}` : '--'
    return [
      <span key={m.symbol} className="cursor-pointer text-rldc-teal-primary hover:underline font-bold" onClick={() => onSymbolClick?.(m.symbol)}>{m.symbol}</span>,
      m.price?.toFixed(2),
      m.price_change?.toFixed(2),
      `${m.price_change_percent?.toFixed(2)}%`,
      m.volume?.toFixed(2),
      buyRange,
      sellRange,
      q ? q.weight : '--',
      q ? q.volatility : '--',
    ]
  })
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Rynki" description="Aktualne ceny i zakresy algorytmu — gdzie bot rozważa kupno lub sprzedaż poszczególnych par." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={15000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {rows.length === 0 && !loading && !error && <EmptyState reason="no-data" detail="Brak danych rynkowych." />}
      {rows.length > 0 && (
        <SimpleTable
          title="Przegląd Rynku"
          headers={['Symbol', 'Cena', 'Zmiana', 'Zmiana %', 'Wolumen', 'BUY zakres', 'SELL zakres', 'Waga Q', 'Vol Q']}
          rows={rows}
        />
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════
// DIAGNOSTYKA WYJŚĆ
// ═══════════════════════════════════════════════════════════════════════════
function ExitDiagnosticsView({ mode }: { mode: 'demo' | 'live' }) {
  const { data: readiness, loading: loadReadiness, error: errReadiness, lastUpdated: luReadiness } =
    useFetch<any>(`/api/signals/entry-readiness?mode=${mode}`, 20000)
  const { data: consistency, loading: loadCons, error: errCons, lastUpdated: luCons } =
    useFetch<any>(`/api/debug/state-consistency?mode=${mode}`, 30000)
  const { data: exitsData, loading: loadExits, error: errExits, lastUpdated: luExits } =
    useFetch<any>(`/api/debug/last-exits?mode=${mode}&limit=20`, 60000)

  const exits: any[] = exitsData?.exits ?? []
  const candidates: any[] = readiness?.candidates ?? []
  const blocked: any[] = readiness?.blocked ?? []

  const pnlCls = (v: number) =>
    v > 0 ? 'text-rldc-green-primary' : v < 0 ? 'text-rldc-red-primary' : 'text-slate-400'

  return (
    <div className="flex-1 p-4 lg:p-6 overflow-y-auto">
      <ViewHeader
        title="Diagnostyka wejść i wyjść"
        description="Stan gotowości bota do otwierania pozycji, spójność portfela oraz historia ostatnich zamknięć."
      />

      {/* ━━━ BANER GOTOWOŚCI DO WEJŚCIA ━━━ */}
      <div className="mb-6">
        <h3 className="text-xs uppercase tracking-widest text-slate-500 mb-3">Gotowość do wejścia</h3>
        <DataStatus loading={loadReadiness} error={errReadiness} lastUpdated={luReadiness} refreshMs={20000} />
        {readiness && (
          <>
            {/* Główny baner */}
            <div className={`rounded-xl border-2 px-5 py-4 mb-4 ${
              readiness.can_enter_now
                ? 'bg-rldc-green-primary/8 border-rldc-green-primary/30'
                : readiness.blocked_count > 0 || readiness.ready_count > 0
                  ? 'bg-amber-500/8 border-amber-500/30'
                  : 'bg-slate-500/5 border-slate-500/20'
            }`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Status wejść</div>
                  <div className={`text-xl font-black ${
                    readiness.can_enter_now ? 'text-rldc-green-primary'
                    : readiness.blocked_count > 0 ? 'text-amber-400'
                    : 'text-slate-400'
                  }`}>
                    {readiness.can_enter_now ? '✅ ' : readiness.blocked_count > 0 ? '⚠️ ' : '⏸ '}
                    {readiness.status_pl ?? '--'}
                  </div>
                </div>
                <div className="flex gap-4 text-center">
                  <div>
                    <div className="text-[10px] uppercase text-slate-500">Gotowych</div>
                    <div className="text-2xl font-bold text-rldc-green-primary">{readiness.ready_count ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase text-slate-500">Zablokowanych</div>
                    <div className="text-2xl font-bold text-amber-400">{readiness.blocked_count ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase text-slate-500">Wolna gotówka</div>
                    <div className="text-lg font-bold text-slate-200">{readiness.cash_available != null ? `${readiness.cash_available.toFixed(0)} EUR` : '--'}</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Kandydaci gotowi do wejścia */}
            {candidates.length > 0 && (
              <div className="mb-3">
                <div className="text-xs text-rldc-green-primary font-semibold mb-2">Kandydaci gotowi do wejścia ({candidates.length})</div>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-xs">
                    <thead>
                      <tr className="text-[10px] uppercase tracking-widest text-slate-500 border-b border-rldc-dark-border">
                        <th className="text-left py-1 pr-4">Symbol</th>
                        <th className="text-right pr-4">Score</th>
                        <th className="text-right pr-4">Pewność</th>
                        <th className="text-right pr-4">Sygnał</th>
                        <th className="text-left">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {candidates.map((c: any, i: number) => (
                        <tr key={i} className="border-b border-rldc-dark-border/30 hover:bg-white/2">
                          <td className="py-1 pr-4 font-bold text-slate-100">{c.symbol}</td>
                          <td className="text-right pr-4 font-mono text-rldc-teal-primary">{c.score?.toFixed(1) ?? '--'}</td>
                          <td className="text-right pr-4 font-mono text-slate-300">{c.confidence != null ? `${Math.round(c.confidence * 100)}%` : '--'}</td>
                          <td className="text-right pr-4 text-slate-400">{c.signal_type ?? '--'}</td>
                          <td className="text-emerald-400 font-semibold">✓ GOTOWY</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Zablokowane */}
            {blocked.length > 0 && (
              <div>
                <div className="text-xs text-amber-400 font-semibold mb-2">Zablokowane ({blocked.length})</div>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-xs">
                    <thead>
                      <tr className="text-[10px] uppercase tracking-widest text-slate-500 border-b border-rldc-dark-border">
                        <th className="text-left py-1 pr-4">Symbol</th>
                        <th className="text-right pr-4">Score</th>
                        <th className="text-right pr-4">Pewność</th>
                        <th className="text-left">Powód blokady</th>
                      </tr>
                    </thead>
                    <tbody>
                      {blocked.slice(0, 10).map((b: any, i: number) => (
                        <tr key={i} className="border-b border-rldc-dark-border/30 hover:bg-white/2">
                          <td className="py-1 pr-4 font-bold text-slate-300">{b.symbol}</td>
                          <td className="text-right pr-4 font-mono text-slate-400">{b.score?.toFixed(1) ?? '--'}</td>
                          <td className="text-right pr-4 font-mono text-slate-500">{b.confidence != null ? `${Math.round(b.confidence * 100)}%` : '--'}</td>
                          <td className="text-amber-300">{b.reason_pl ?? b.block_reason ?? '--'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Panel spójności stanu */}
      <div className="mb-6">
        <h3 className="text-xs uppercase tracking-widest text-slate-500 mb-3">Spójność stanu portfela</h3>
        <DataStatus loading={loadCons} error={errCons} lastUpdated={luCons} refreshMs={30000} />
        {consistency && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
              {[
                { label: 'Transakcje kupna', value: consistency.orders_buy_filled, color: 'text-emerald-400' },
                { label: 'Transakcje sprzedaży', value: consistency.orders_sell_filled, color: 'text-rose-400' },
                { label: 'Otwarte pozycje', value: consistency.positions_count, color: 'text-amber-400' },
                { label: 'Zmiana equity', value: consistency.equity_change != null ? `${consistency.equity_change >= 0 ? '+' : ''}${consistency.equity_change.toFixed(2)} EUR` : '--', color: consistency.equity_change >= 0 ? 'text-emerald-400' : 'text-rose-400' },
              ].map(({ label, value, color }) => (
                <div key={label} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
                  <div className={`text-xl font-bold font-mono ${color}`}>{String(value ?? '--')}</div>
                </div>
              ))}
            </div>
            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card mb-2">
              <div className="text-xs text-slate-300 font-semibold mb-1">{consistency.diagnosis}</div>
              <div className="text-xs text-slate-400">{consistency.explanation}</div>
            </div>
            {consistency.inconsistencies?.length > 0 && (
              <div className="space-y-1">
                {consistency.inconsistencies.map((msg: string, i: number) => (
                  <div key={i} className="text-xs text-amber-300 bg-amber-900/20 border border-amber-800/40 rounded px-3 py-2">
                    ⚠ {msg}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Historia wyjść */}
      <div>
        <h3 className="text-xs uppercase tracking-widest text-slate-500 mb-3">Ostatnie zamknięcia pozycji</h3>
        <DataStatus loading={loadExits} error={errExits} lastUpdated={luExits} refreshMs={60000} />
        {!loadExits && exits.length === 0 && (
          <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-8 text-center text-slate-500 text-sm">
            Brak zamkniętych pozycji w historii.
          </div>
        )}
        <div className="space-y-2">
          {exits.map((ex: any, i: number) => (
            <div key={i} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="flex flex-wrap items-center gap-2 mb-1">
                <span className="text-sm font-bold text-slate-100">{ex.symbol}</span>
                {ex.premature_exit && (
                  <span className="text-[10px] bg-amber-800/40 text-amber-300 border border-amber-700/50 rounded px-1.5 py-0.5 font-semibold">
                    ZA WCZEŚNIE
                  </span>
                )}
                <span className={`text-xs font-mono font-semibold ${pnlCls(ex.pnl_eur)}`}>
                  {ex.pnl_eur >= 0 ? '+' : ''}{ex.pnl_eur?.toFixed(2)} EUR ({ex.pnl_pct >= 0 ? '+' : ''}{ex.pnl_pct?.toFixed(2)}%)
                </span>
                <span className="ml-auto text-[10px] text-slate-500">
                  {ex.held_duration_h != null ? `${ex.held_duration_h.toFixed(1)}h` : ''}
                </span>
              </div>
              <div className="text-xs text-slate-400 mb-1">
                <span className="text-slate-500">Powód: </span>
                <span className="text-slate-200">{ex.reason_pl || ex.reason_code || '--'}</span>
                <span className="text-slate-600 ml-2">({ex.reason_code})</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-0.5 text-[11px] text-slate-500">
                <span>Wejście: <span className="text-slate-300">{ex.entry_price?.toFixed?.(4) ?? '--'}</span></span>
                <span>Wyjście: <span className="text-slate-300">{ex.exit_price?.toFixed?.(4) ?? '--'}</span></span>
                {ex.post_exit_move_pct != null && (
                  <span>
                    Po wyjściu: <span className={ex.post_exit_move_pct > 2 ? 'text-amber-400' : 'text-slate-300'}>
                      {ex.post_exit_move_pct > 0 ? '+' : ''}{ex.post_exit_move_pct.toFixed(2)}%
                    </span>
                  </span>
                )}
                {ex.gave_back_pct != null && ex.gave_back_pct > 0 && (
                  <span>Oddano: <span className="text-rose-400">-{ex.gave_back_pct.toFixed(2)}%</span></span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function TradeDeskView({ mode }: { mode: 'demo' | 'live' }) {
  const [symbolFilter, setSymbolFilter] = useState<string>('ALL')
  const [rangeHours, setRangeHours] = useState<number>(24)
  const { data: orders, loading: loadingOrders, error: errorOrders } = useFetch<any>(`/api/orders?mode=${mode}&limit=200`, 30000)
  const { data: positions, loading: loadingPos, error: errorPos } = useFetch<any>(`/api/positions?mode=${mode}`, 30000)
  const rawOrders = orders?.data || []
  const filteredOrders = rawOrders.filter((o: any) => {
    const ts = new Date(o.timestamp).getTime()
    const cutoff = Date.now() - rangeHours * 60 * 60 * 1000
    const matchTime = ts >= cutoff
    const matchSymbol = symbolFilter === 'ALL' ? true : o.symbol === symbolFilter
    return matchTime && matchSymbol
  })
  const symbols: string[] = Array.from(new Set(rawOrders.map((o: any) => String(o.symbol))))
  const orderRows = filteredOrders.map((o: any) => [
    o.symbol,
    o.side,
    o.type,
    o.quantity,
    o.status,
    o.timestamp,
    o.reason ? String(o.reason) : '--',
  ])
  const isLive = mode === 'live'
  const posData: any[] = positions?.data || []
  const positionHeaders = isLive
    ? ['Symbol', 'Kierunek', 'Ilość', 'Cena EUR', 'Wartość EUR', 'Źródło']
    : ['Symbol', 'Kierunek', 'Ilość', 'Cena zakupu', 'Cena teraz', 'Wynik (EUR)']
  const positionRows = posData.map((p: any) =>
    isLive
      ? [
          p.symbol,
          p.side || 'LONG',
          typeof p.quantity === 'number' ? p.quantity.toFixed(8) : p.quantity,
          p.current_price != null ? p.current_price.toFixed(p.current_price < 1 ? 6 : 2) : '--',
          p.value_eur != null ? `${p.value_eur.toFixed(2)} EUR` : '--',
          p.source === 'binance_spot' ? 'LIVE Spot' : 'Lokalna',
        ]
      : [
          p.symbol,
          p.side,
          p.quantity,
          p.entry_price?.toFixed(2),
          p.current_price?.toFixed(2),
          p.unrealized_pnl?.toFixed(2),
        ]
  )
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Panel transakcyjny" description="Przeglądaj zlecenia i otwarte pozycje." />
      {(loadingOrders || loadingPos) && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {(errorOrders || errorPos) && <div className="text-sm text-rldc-red-primary mb-4">Nie udało się pobrać danych</div>}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border neon-card">
          <div className="flex flex-wrap items-center gap-4">
            <div className="text-xs text-slate-500">Filtry:</div>
            <select
              title="Filtr par"
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
              className="bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 text-xs rounded px-2 py-1"
            >
              <option value="ALL">Wszystkie pary</option>
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              title="Zakres czasu"
              value={rangeHours}
              onChange={(e) => setRangeHours(Number(e.target.value))}
              className="bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 text-xs rounded px-2 py-1"
            >
              <option value={1}>Ostatnia 1h</option>
              <option value={24}>Ostatnie 24h</option>
              <option value={168}>Ostatni tydzień</option>
            </select>
          </div>
        </div>
        <div className="col-span-12">
          <SimpleTable
            title="Zlecenia (ostatnie)"
            headers={['Symbol', 'Kierunek', 'Rodzaj', 'Ilość', 'Status', 'Czas', 'Powód']}
            rows={orderRows}
          />
        </div>
        <div className="col-span-12">
          <SimpleTable
            title={isLive ? 'Pozycje LIVE Spot (Binance)' : 'Otwarte pozycje'}
            headers={positionHeaders}
            rows={positionRows}
          />
        </div>
      </div>
    </div>
  )
}

function PortfolioView({ mode, onSymbolClick }: { mode: 'demo' | 'live'; onSymbolClick?: (s: string) => void }) {
  const { data: wealth, loading, error, lastUpdated } = useFetch<any>(`/api/portfolio/wealth?mode=${mode}`, 30000)
  const { data: forecast } = useFetch<any>(`/api/portfolio/forecast?mode=${mode}`, 60000)

  const fmtPrice = (v: number) =>
    v == null ? '--' : v < 0.0001 ? v.toFixed(8) : v < 1 ? v.toFixed(6) : v < 100 ? v.toFixed(4) : v.toFixed(2)
  const fmtEur = (v: number | null | undefined) =>
    v == null ? '--' : `${v.toFixed(2)} EUR`
  const pnlCls = (v: number) => v >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'

  const kpiCards = [
    { label: 'Wartość konta', value: fmtEur(wealth?.total_equity), color: 'text-slate-100' },
    { label: 'Wolna gotówka', value: fmtEur(wealth?.free_cash), color: 'text-slate-200' },
    {
      label: 'Wynik na pozycjach',
      value: wealth?.total_pnl != null ? `${wealth.total_pnl >= 0 ? '+' : ''}${wealth.total_pnl.toFixed(2)} EUR` : '--',
      color: wealth?.total_pnl != null ? pnlCls(wealth.total_pnl) : 'text-slate-400',
    },
    {
      label: 'Aktywne pozycje',
      value: wealth?.positions_count != null
        ? `${wealth.positions_count}${wealth.dust_positions_count > 0 ? ` (+${wealth.dust_positions_count} pył)` : ''}`
        : '--',
      color: 'text-slate-200',
    },
  ]

  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Portfel" description="Całkowity majątek, skład portfela i prognoza wartości." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={30000} />
      </div>

      {/* Info: LIVE bez kluczy Binance */}
      {wealth?._info && (
        <div className="mb-4 bg-amber-500/10 border border-amber-500/50 text-amber-300 px-4 py-3 rounded-lg text-sm">
          {wealth._info}
        </div>
      )}

      {error && <EmptyState reason="sync-stopped" detail={error} />}

      {/* KPI summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {kpiCards.map(card => (
          <div key={card.label} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">{card.label}</div>
            <div className={`text-lg font-bold font-mono mt-1 ${card.color}`}>{card.value}</div>
          </div>
        ))}
      </div>

      {/* Prognoza portfela */}
      {forecast && (
        <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border p-4 mb-5">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs font-semibold text-slate-300">Prognoza wartości portfela</div>
            <div className="text-[10px] text-slate-500">
              pewność: <span className={
                forecast.confidence === 'wysoka' ? 'text-rldc-green-primary' :
                forecast.confidence === 'średnia' ? 'text-yellow-400' :
                forecast.confidence === 'niska' ? 'text-rldc-red-primary' : 'text-slate-500'
              }>{forecast.confidence || '--'}</span>
              {forecast.total_symbols > 0 && (
                <span className="ml-2">({forecast.symbols_with_forecast}/{forecast.total_symbols} symboli)</span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Za 1 godzinę', value: forecast.forecast_1h },
              { label: 'Za 2 godziny', value: forecast.forecast_2h },
              { label: 'Za 7 dni *', value: forecast.forecast_7d },
            ].map(({ label, value }) => {
              const current = forecast.current_value || 0
              const diff = value != null ? value - current : null
              const pct = diff != null && current > 0 ? (diff / current * 100) : null
              return (
                <div key={label} className="terminal-card border border-rldc-dark-border rounded-lg px-3 py-3">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="text-base font-mono font-bold text-slate-100 mt-1">{fmtEur(value)}</div>
                  {diff != null && (
                    <div className={`text-xs mt-0.5 ${diff >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>
                      {diff >= 0 ? '+' : ''}{diff.toFixed(2)} EUR
                      {pct != null && <span className="ml-1 opacity-70">({pct >= 0 ? '+' : ''}{pct.toFixed(1)}%)</span>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          {forecast.confidence === 'brak danych' && (
            <div className="mt-3 text-xs text-slate-500">
              Brak prognoz AI dla symboli w portfelu. Poczekaj na pierwsze cykle zbierania danych lub sprawdź połączenie z API.
            </div>
          )}
          <div className="mt-2 text-[10px] text-slate-600">* Za 7 dni — ekstrapolacja na bazie prognozy 24h (wartość szacunkowa)</div>
        </div>
      )}

      {/* Wykres portfela (historia equity) */}
      {(wealth?.equity_history?.length ?? 0) > 1 && (() => {
        const { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } = require('recharts')
        const histData = wealth.equity_history
        const vals = histData.map((d: any) => d.equity)
        const minE = Math.min(...vals) * 0.998
        const maxE = Math.max(...vals) * 1.002
        return (
          <div className="bg-rldc-dark-card rounded-lg border border-rldc-dark-border p-4 mb-5">
            <div className="text-xs font-semibold text-slate-300 mb-3">Historia wartości konta (ostatnie 48h)</div>
            <ResponsiveContainer width="100%" height={120}>
              <LineChart data={histData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="t" tick={{ fontSize: 9, fill: '#64748b' }} interval="preserveStartEnd" />
                <YAxis domain={[minE, maxE]} tick={{ fontSize: 9, fill: '#64748b' }} width={56} tickFormatter={(v: number) => v.toFixed(0)} />
                <Tooltip
                  contentStyle={{ background: '#0f1923', border: '1px solid #1e2d3d', fontSize: 10 }}
                  formatter={(v: any) => [`${Number(v).toFixed(2)} EUR`, 'Wartość konta']}
                />
                <Line type="monotone" dataKey="equity" stroke="#2dd4bf" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )
      })()}

      {/* Skład portfela */}
      <div className="terminal-card rounded-lg border border-rldc-dark-border p-4 mb-5">
        <h2 className="text-sm font-semibold text-slate-200 mb-3">Skład portfela</h2>
        {!loading && (wealth?.items?.length ?? 0) === 0 && !error && (
          <EmptyState reason="no-data" detail="Brak otwartych pozycji w portfelu." />
        )}
        {(wealth?.items?.length ?? 0) > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px] font-mono">
              <thead>
                <tr className="border-b border-rldc-dark-border text-left text-[10px] uppercase tracking-widest text-slate-500">
                  <th className="pb-2 font-medium">Symbol</th>
                  <th className="pb-2 font-medium text-right">Ilość</th>
                  <th className="pb-2 font-medium text-right">Kupiono (EUR)</th>
                  <th className="pb-2 font-medium text-right">Teraz (EUR)</th>
                  <th className="pb-2 font-medium text-right">Wartość</th>
                  <th className="pb-2 font-medium text-right">Udział</th>
                  <th className="pb-2 font-medium text-right">Wynik</th>
                </tr>
              </thead>
              <tbody>
                {(wealth.items || []).map((item: any) => (
                  <tr key={item.symbol} className="border-b border-rldc-dark-border/50 hover:bg-rldc-dark-hover transition">
                    <td className="py-2">
                      <button
                        className="text-rldc-teal-primary hover:underline font-bold"
                        onClick={() => onSymbolClick?.(item.symbol)}
                      >
                        {item.symbol.replace(/EUR$/, '/EUR').replace(/USDT$/, '/USDT').replace(/USDC$/, '/USDC')}
                      </button>
                    </td>
                    <td className="py-2 text-slate-300 text-right">
                      {item.quantity < 1 ? item.quantity.toFixed(6) : item.quantity < 10 ? item.quantity.toFixed(4) : item.quantity.toFixed(2)}
                    </td>
                    <td className="py-2 text-slate-400 text-right">{fmtPrice(item.entry_price)}</td>
                    <td className="py-2 text-slate-300 text-right">{fmtPrice(item.current_price)}</td>
                    <td className="py-2 text-slate-200 text-right font-semibold">{item.value_eur.toFixed(2)} EUR</td>
                    <td className="py-2 text-slate-400 text-right">{item.weight_pct}%</td>
                    <td className={`py-2 text-right font-semibold ${pnlCls(item.pnl_eur)}`}>
                      {item.pnl_eur != null ? `${item.pnl_eur >= 0 ? '+' : ''}${item.pnl_eur.toFixed(2)} EUR` : '--'}
                      <span className="text-[10px] ml-1 opacity-70">({item.pnl_pct >= 0 ? '+' : ''}{item.pnl_pct}%)</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function StrategiesView({ onSymbolClick }: { onSymbolClick?: (s: string) => void }) {
  const { data, loading, error, lastUpdated } = useFetch<any>(`/api/signals/top10`, 20000)
  const rows = (data?.data || []).map((s: any) => [
    <span key={s.symbol} className="cursor-pointer text-rldc-teal-primary hover:underline font-bold" onClick={() => onSymbolClick?.(s.symbol)}>{s.symbol}</span>,
    signalLabel(s.signal_type),
    `${Math.round(s.confidence * 100)}%`,
    s.price?.toFixed(2),
    s.timestamp,
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Strategie" description="Pary z najsilniejszymi sygnałami — kandydaci do wejścia w pozycję." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={20000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {rows.length === 0 && !loading && !error && <EmptyState reason="no-data" detail="Brak aktywnych sygnałów." />}
      {rows.length > 0 && (
        <SimpleTable
          title="Top 10 sygnałów"
          headers={['Symbol', 'Sygnał', 'Pewność sygnału', 'Cena (EUR)', 'Czas']}
          rows={rows}
        />
      )}
    </div>
  )
}

function SignalsView({ onSymbolClick }: { onSymbolClick?: (s: string) => void }) {
  const { data, loading, error, lastUpdated } = useFetch<any>(`/api/signals/latest?limit=20`, 15000)
  const rows = (data?.data || []).map((s: any) => [
    <span key={s.symbol} className="cursor-pointer text-rldc-teal-primary hover:underline font-bold" onClick={() => onSymbolClick?.(s.symbol)}>{s.symbol}</span>,
    signalLabel(s.signal_type),
    `${Math.round(s.confidence * 100)}%`,
    s.price?.toFixed(2),
    s.timestamp,
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="AI i Sygnały" description="Ostatnie sygnały generowane przez algorytm analizy rynku." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={15000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {rows.length === 0 && !loading && !error && <EmptyState reason="no-data" detail="Algorytm nie wygenerował jeszcze sygnałów." />}
      {rows.length > 0 && (
        <SimpleTable
          title="Najnowsze sygnały"
          headers={['Symbol', 'Sygnał', 'Pewność sygnału', 'Cena (EUR)', 'Czas']}
          rows={rows}
        />
      )}
    </div>
  )
}

function DecisionsView({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading } = useFetch<any>(`/api/portfolio/wealth?mode=${mode}`, 30000)
  const { data: risk } = useFetch<any>(`/api/account/risk?mode=${mode}`, 30000)
  const fmt = (v: any) => typeof v === 'number' ? v.toFixed(2) + ' EUR' : '--'
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Kondycja konta" description="Aktualny wynik finansowy, wolne środki i stan limitów bezpieczeństwa." />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {data?._info && (
        <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-400 leading-relaxed">
          ⚠ {data._info}
        </div>
      )}
      {!data && !loading && mode === 'live' && (
        <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-400 leading-relaxed">
          LIVE aktywny — brak danych z Binance. Ustaw klucze API w pliku .env
        </div>
      )}
      {risk?.data?.daily_loss_triggered && (
        <div className="mb-4 bg-rldc-red-primary/20 border border-rldc-red-primary text-rldc-red-primary px-4 py-3 rounded">
          Limit dziennej straty przekroczony — handel wstrzymany.
        </div>
      )}
      {risk?.data?.drawdown_triggered && (
        <div className="mb-4 bg-yellow-500/20 border border-yellow-500 text-yellow-400 px-4 py-3 rounded">
          Drawdown przekroczony na pozycji — sprawdź ryzyko.
        </div>
      )}
      <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
        <h2 className="text-lg font-semibold mb-4 text-slate-200">Stan konta</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-slate-500 mb-1">Wartość konta</div>
            <div className="text-lg font-bold text-slate-100">{fmt(data?.total_equity)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Wynik na pozycjach</div>
            <div className={`text-lg font-bold ${(data?.total_pnl ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>{fmt(data?.total_pnl)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Wolne środki</div>
            <div className="text-lg font-bold text-slate-100">{fmt(data?.free_cash)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Poziom zabezpieczenia</div>
            <div className="text-lg font-bold text-slate-100">{typeof data?.margin_level === 'number' ? data.margin_level.toFixed(2) + '%' : '--'}</div>
          </div>
        </div>
      </div>
      <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border mt-4 neon-card">
        <h2 className="text-lg font-semibold mb-4 text-slate-200">Limity ryzyka</h2>
        <div className="grid grid-cols-2 gap-4 text-sm text-slate-300">
          <div>Maks. dzienna strata: <span className="font-mono text-slate-100">{risk?.data?.max_daily_loss_pct ?? '--'}%</span></div>
          <div>Limit dzienny: <span className="font-mono text-slate-100">{risk?.data?.daily_loss_limit ?? '--'} EUR</span></div>
          <div>Maks. obsunięcie wartości: <span className="font-mono text-slate-100">{risk?.data?.max_drawdown_pct ?? '--'}%</span></div>
          <div>Najwyższe obsunięcie (hist.): <span className="font-mono text-slate-100">{risk?.data?.worst_drawdown_pct ?? '--'}%</span></div>
        </div>
      </div>
    </div>
  )
}

function RiskView({ mode, onSymbolClick }: { mode: 'demo' | 'live'; onSymbolClick?: (s: string) => void }) {
  const { data: risk, loading, error, lastUpdated } = useFetch<any>(`/api/account/risk?mode=${mode}`, 30000)
  const { data: analysis } = useFetch<any>(`/api/positions/analysis?mode=${mode}`, 30000)
  const r = risk?.data
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Ryzyko" description="Sprawdź, czy bot działa bezpiecznie i czy nie ryzykuje za dużo." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={30000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {r?.daily_loss_triggered && (
        <div className="mb-4 bg-rldc-red-primary/20 border border-rldc-red-primary text-rldc-red-primary px-4 py-3 rounded font-semibold">
          ⚠ Limit dziennej straty przekroczony — trading wstrzymany.
        </div>
      )}
      {r?.drawdown_triggered && (
        <div className="mb-4 bg-yellow-500/20 border border-yellow-500 text-yellow-400 px-4 py-3 rounded">
          ⚠ Drawdown przekroczony — sprawdź pozycje.
        </div>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          { label: 'Maks. dzienna strata', value: `${r?.max_daily_loss_pct ?? '--'}%` },
          { label: 'Limit straty dziennej (EUR)', value: r?.daily_loss_limit ?? '--' },
          { label: 'Maks. obsunięcie wartości', value: `${r?.max_drawdown_pct ?? '--'}%` },
          { label: 'Najwyższe obsunięcie (hist.)', value: `${r?.worst_drawdown_pct ?? '--'}%` },
          { label: 'Wynik na pozycjach', value: typeof r?.unrealized_pnl === 'number' ? r.unrealized_pnl.toFixed(4) + ' EUR' : '--' },
          { label: 'Pozycje', value: r?.positions_count ?? '--' },
        ].map((k) => (
          <div key={k.label} className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">{k.label}</div>
            <div className="text-lg font-semibold font-mono text-slate-100 mt-1">{String(k.value)}</div>
          </div>
        ))}
      </div>
      {(analysis?.data || []).length > 0 && (
        <SimpleTable
          title="Otwarte pozycje — analiza ryzyka"
          headers={['Symbol', 'Decyzja', 'Wynik %', 'RSI', 'Trend', 'Powody']}
          rows={(analysis.data).map((c: any) => [
            <span key={c.symbol} className="cursor-pointer text-rldc-teal-primary hover:underline font-bold" onClick={() => onSymbolClick?.(c.symbol)}>{c.symbol}</span>,
            <span key={c.symbol} className={c.decision === 'SPRZEDAJ' ? 'text-rldc-red-primary font-bold' : c.decision === 'TRZYMAJ' ? 'text-rldc-green-primary font-bold' : 'text-slate-300'}>{c.decision}</span>,
            `${c.pnl_pct ?? '--'}%`,
            c.rsi ?? '--',
            c.trend ?? '--',
            (c.reasons || []).slice(0, 2).join(' · ') || '--',
          ])}
        />
      )}
    </div>
  )
}

function BacktestView({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading, error } = useFetch<any>(`/api/orders/stats?mode=${mode}&days=30`, 60000)
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Historia zleceń" description="Jak działały zlecenia w ostatnim czasie — ile wykonanych, ile odrzuconych." />
      {loading && <div className="text-sm text-slate-400 mb-4">Wczytywanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
        <h2 className="text-lg font-semibold mb-4 text-slate-200">Statystyki zleceń (ostatnie 30 dni)</h2>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <div className="text-xs text-slate-500 mb-1">Łącznie</div>
            <div className="text-lg font-bold text-slate-100">{data?.data?.total || 0}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Wykonane</div>
            <div className="text-lg font-bold text-rldc-green-primary">{data?.data?.filled || 0}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Wskaźnik wykonania</div>
            <div className="text-lg font-bold text-slate-100">{data?.data?.fill_rate || 0}%</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function MarketProxyView({ activeView, mode }: { activeView: string; mode: 'demo' | 'live' }) {
  if (activeView === 'economics') return <EconomicsSubView mode={mode} />
  if (activeView === 'alerts') return <AlertsSubView />
  if (activeView === 'news') return <NewsSubView />
  return <div className="flex-1 p-6"><EmptyState reason="not-connected" /></div>
}

function EconomicsSubView({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading, error, lastUpdated } = useFetch<any>(`/api/account/analytics/overview?mode=${mode}`, 60000)
  const d = data?.data || {}
  const r = d.risk_snapshot || {}
  const a = d.account_state || {}
  const kpi = [
    { label: 'Zysk brutto', value: `${(d.gross_pnl ?? 0).toFixed(2)} EUR`, color: (d.gross_pnl ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
    { label: 'Zysk netto', value: `${(d.net_pnl ?? 0).toFixed(2)} EUR`, color: (d.net_pnl ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
    { label: 'Koszty łączne', value: `${(d.total_cost ?? 0).toFixed(2)} EUR`, color: 'text-amber-400' },
    { label: 'Win rate netto', value: `${((d.net_win_rate ?? 0) * 100).toFixed(1)}%`, color: (d.net_win_rate ?? 0) >= 0.5 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
    { label: 'Expectancy', value: `${(d.net_expectancy ?? 0).toFixed(4)} EUR`, color: (d.net_expectancy ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
    { label: 'Profit Factor', value: `${(d.profit_factor_net ?? 0).toFixed(2)}`, color: (d.profit_factor_net ?? 0) >= 1 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
    { label: 'Max Drawdown', value: `${(d.drawdown_net ?? 0).toFixed(2)} EUR`, color: 'text-rldc-red-primary' },
    { label: 'Zablokowanych decyzji', value: String(d.blocked_decisions_count ?? 0), color: 'text-slate-400' },
    { label: 'Retencja brutto→netto', value: `${((d.gross_to_net_retention_ratio ?? 0) * 100).toFixed(1)}%`, color: (d.gross_to_net_retention_ratio ?? 0) >= 0.7 ? 'text-rldc-green-primary' : 'text-amber-400' },
    { label: 'Overtrading score', value: `${((d.overtrading_score ?? 0) * 100).toFixed(1)}%`, color: (d.overtrading_score ?? 0) <= 0.35 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
    { label: 'Ubytek brutto→netto', value: `${(d.gross_net_gap ?? 0).toFixed(2)} EUR`, color: 'text-amber-400' },
  ]
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Ekonomia" description="Koszty, zyski i wskaźniki efektywności tradingu." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={60000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {!loading && !error && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            {kpi.map(k => (
              <div key={k.label} className="bg-rldc-dark-card rounded-lg p-3 border border-rldc-dark-border">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">{k.label}</div>
                <div className={`text-lg font-bold font-mono mt-1 ${k.color}`}>{k.value}</div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border">
              <div className="text-xs font-semibold text-slate-300 mb-3">Struktura kosztów</div>
              {[
                { label: 'Opłaty (fee)', val: d.fee_cost ?? 0 },
                { label: 'Poślizg (slippage)', val: d.slippage_cost ?? 0 },
                { label: 'Spread', val: d.spread_cost ?? 0 },
              ].map(c => (
                <div key={c.label} className="flex justify-between text-xs py-1.5 border-b border-rldc-dark-border/60">
                  <span className="text-slate-400">{c.label}</span>
                  <span className="text-amber-400 font-mono">{c.val.toFixed(4)} EUR</span>
                </div>
              ))}
            </div>
            <div className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border">
              <div className="text-xs font-semibold text-slate-300 mb-3">Stan konta</div>
              {[
                { label: 'Equity', val: `${(a.equity ?? 0).toFixed(2)} EUR` },
                { label: 'Wolna gotówka', val: `${(a.cash ?? 0).toFixed(2)} EUR` },
                { label: 'Wartość pozycji', val: `${(a.positions_value ?? 0).toFixed(2)} EUR` },
                { label: 'Ekspozycja łączna', val: `${(r.total_exposure ?? 0).toFixed(2)} EUR` },
                { label: 'Otwarte pozycje', val: String(r.open_positions_count ?? 0) },
              ].map(c => (
                <div key={c.label} className="flex justify-between text-xs py-1.5 border-b border-rldc-dark-border/60">
                  <span className="text-slate-400">{c.label}</span>
                  <span className="text-slate-200 font-mono">{c.val}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function AlertsSubView() {
  const { data, loading, error, lastUpdated } = useFetch<any>('/api/account/system-logs?limit=80', 30000)
  const warnings = (data?.data || []).filter((l: any) => l.level === 'WARNING' || l.level === 'ERROR')
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Alerty" description="Ostrzeżenia i błędy systemu." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={30000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {warnings.length === 0 && !loading && <EmptyState reason="no-data" detail="Brak alertów — system działa prawidłowo." />}
      {warnings.length > 0 && (
        <div className="space-y-2">
          {warnings.map((l: any, i: number) => (
            <div key={i} className={`rounded-lg p-3 border text-xs ${l.level === 'ERROR' ? 'bg-rldc-red-primary/10 border-rldc-red-primary/30' : 'bg-amber-500/10 border-amber-500/30'}`}>
              <div className="flex justify-between items-start">
                <div className="flex items-center gap-2">
                  <span className={`font-bold ${l.level === 'ERROR' ? 'text-rldc-red-primary' : 'text-amber-400'}`}>{l.level}</span>
                  <span className="text-slate-400">{l.module}</span>
                </div>
                <span className="text-[10px] text-slate-500">{(l.timestamp || '').replace('T', ' ').slice(0, 19)}</span>
              </div>
              <div className="text-slate-300 mt-1 break-all">{(l.message || '').slice(0, 300)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function NewsSubView() {
  const { data, loading, error, lastUpdated } = useFetch<any>('/api/blog/list?limit=20', 60000)
  const posts = data?.data || []
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Wiadomości" description="Analiza rynkowa AI — najnowsze wpisy i sygnały." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={60000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {posts.length === 0 && !loading && <EmptyState reason="no-data" detail="Brak analiz rynkowych." />}
      {posts.length > 0 && (
        <div className="space-y-3">
          {posts.map((p: any) => (
            <div key={p.id} className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border hover:border-rldc-teal-primary/30 transition">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-slate-200">{p.title}</span>
                <span className="text-[10px] text-slate-500">{(p.created_at || '').replace('T', ' ').slice(0, 16)}</span>
              </div>
              <div className="text-xs text-slate-400 leading-relaxed">{p.summary || 'Brak podsumowania.'}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────
 *  WIDOK: Centrum diagnostyki — terminal + aktywność + ślad AI
 * ───────────────────────────────────────────────── */
function DiagnosticHubView({ mode }: { mode: 'demo' | 'live' }) {
  const [tab, setTab] = useState<'terminal' | 'activity' | 'trace' | 'trading'>('terminal')

  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Centrum diagnostyki" description="Terminal systemu, aktywność bota, ślad decyzji AI i status handlu." />
      </div>

      {/* Zakładki */}
      <div className="flex gap-2 mb-5 border-b border-rldc-dark-border pb-2">
        {([
          { key: 'terminal', label: 'Terminal' },
          { key: 'activity', label: 'Aktywność bota' },
          { key: 'trace', label: 'Ślad AI' },
          { key: 'trading', label: 'Status handlu' },
        ] as const).map(t => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`px-4 py-1.5 rounded text-xs font-semibold transition ${
              tab === t.key
                ? 'bg-rldc-teal-primary/20 text-rldc-teal-primary border border-rldc-teal-primary/40'
                : 'text-slate-400 hover:text-slate-200 border border-transparent'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'terminal' && <DiagTerminalTab />}
      {tab === 'activity' && <DiagActivityTab mode={mode} />}
      {tab === 'trace' && <DiagTraceTab mode={mode} />}
      {tab === 'trading' && <DiagTradingTab mode={mode} />}
    </div>
  )
}

/* Panel 1: Terminal — logi systemowe */
function DiagTerminalTab() {
  const [level, setLevel] = React.useState<string>('')
  const [paused, setPaused] = React.useState(false)
  const [autoScroll, setAutoScroll] = React.useState(true)
  const [chatInput, setChatInput] = React.useState('')
  const [chatOutput, setChatOutput] = React.useState<any>(null)
  const [chatLoading, setChatLoading] = React.useState(false)
  const [termInput, setTermInput] = React.useState('pwd')
  const [termOutput, setTermOutput] = React.useState<any>(null)
  const [termLoading, setTermLoading] = React.useState(false)
  const containerRef = React.useRef<HTMLDivElement>(null)

  const url = `/api/account/system-logs?limit=100${level ? `&level=${level}` : ''}`
  const { data, loading, error, lastUpdated } = useFetch<any>(paused ? '' : url, 5000)
  const logs: any[] = data?.data || []

  React.useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const levelColor = (l: string) => {
    if (l === 'ERROR' || l === 'CRITICAL') return 'text-rldc-red-primary'
    if (l === 'WARNING') return 'text-yellow-400'
    if (l === 'INFO') return 'text-rldc-green-primary'
    return 'text-slate-500'
  }

  const runAiCommand = async () => {
    const text = chatInput.trim()
    if (!text) return
    setChatLoading(true)
    try {
      const headers = withAdminToken({ 'Content-Type': 'application/json' })
      const res = await fetch(`${getApiBase()}/api/control/command/execute`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          text,
          source: 'web',
          execute_mode: 'execute',
          force: /wymus|teraz/i.test(text),
        }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setChatOutput(json?.data || null)
    } catch (e: any) {
      setChatOutput({ error: e?.message || 'Blad AI command' })
    } finally {
      setChatLoading(false)
    }
  }

  const runTerminalCommand = async () => {
    const command = termInput.trim()
    if (!command) return
    setTermLoading(true)
    try {
      const headers = withAdminToken({ 'Content-Type': 'application/json' })
      const res = await fetch(`${getApiBase()}/api/control/terminal/exec`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ command, timeout_seconds: 6 }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setTermOutput(json?.data || null)
    } catch (e: any) {
      setTermOutput({ error: e?.message || 'Blad terminala' })
    } finally {
      setTermLoading(false)
    }
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={5000} />
        <div className="flex gap-1 ml-auto flex-wrap">
          {(['', 'DEBUG', 'INFO', 'WARNING', 'ERROR'] as const).map(l => (
            <button
              key={l || 'ALL'}
              type="button"
              onClick={() => setLevel(l)}
              className={`px-2 py-0.5 rounded text-[10px] font-bold border transition ${
                level === l
                  ? 'bg-rldc-teal-primary/20 text-rldc-teal-primary border-rldc-teal-primary/40'
                  : 'text-slate-400 border-slate-700 hover:text-slate-200'
              }`}
            >
              {l || 'WSZYSTKIE'}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setPaused(p => !p)}
            className={`px-2 py-0.5 rounded text-[10px] font-bold border transition ${
              paused
                ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/40'
                : 'text-slate-400 border-slate-700 hover:text-slate-200'
            }`}
          >
            {paused ? '▶ WZNÓW' : '⏸ PAUZUJ'}
          </button>
          <button
            type="button"
            onClick={() => setAutoScroll(a => !a)}
            className={`px-2 py-0.5 rounded text-[10px] font-bold border transition ${
              autoScroll
                ? 'bg-teal-500/20 text-teal-400 border-teal-500/40'
                : 'text-slate-400 border-slate-700 hover:text-slate-200'
            }`}
          >
            SCROLL {autoScroll ? 'WŁ' : 'WYŁ'}
          </button>
        </div>
      </div>

      {error && <EmptyState reason="sync-stopped" detail={error} />}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-4">
        <div className="terminal-card rounded-lg border border-rldc-dark-border p-4">
          <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">AI Chat / Command Brain</div>
          <div className="flex gap-2">
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') runAiCommand() }}
              placeholder="np. kup btc wymus / analizuj eth / ustaw ostrozny tryb"
              className="flex-1 bg-[#0a1219] border border-rldc-dark-border rounded px-3 py-2 text-sm text-slate-200"
            />
            <button
              type="button"
              onClick={runAiCommand}
              disabled={chatLoading}
              className="px-3 py-2 rounded text-xs font-semibold border border-rldc-teal-primary/40 text-rldc-teal-primary hover:bg-rldc-teal-primary/10"
            >
              {chatLoading ? 'Przetwarzam...' : 'Wyślij'}
            </button>
          </div>
          <div className="mt-3 bg-[#060d14] border border-rldc-dark-border rounded p-3 text-xs text-slate-300 min-h-[90px] whitespace-pre-wrap">
            {!chatOutput && <span className="text-slate-500">Brak odpowiedzi.</span>}
            {chatOutput?.error && <span className="text-rldc-red-primary">{chatOutput.error}</span>}
            {chatOutput && !chatOutput.error && (
              <>
                <div>Akcja: {chatOutput.action}</div>
                <div>Decyzja: {chatOutput.decision}</div>
                <div>Wynik: {chatOutput.summary}</div>
                {chatOutput.pending_order_id && <div>Pending ID: {chatOutput.pending_order_id}</div>}
              </>
            )}
          </div>
        </div>

        <div className="terminal-card rounded-lg border border-rldc-dark-border p-4">
          <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">Terminal online (guarded)</div>
          <div className="flex gap-2">
            <input
              value={termInput}
              onChange={(e) => setTermInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') runTerminalCommand() }}
              placeholder="Dozwolone: pwd, ls, tail, rg, ps..."
              className="flex-1 bg-[#0a1219] border border-rldc-dark-border rounded px-3 py-2 text-sm text-slate-200"
            />
            <button
              type="button"
              onClick={runTerminalCommand}
              disabled={termLoading}
              className="px-3 py-2 rounded text-xs font-semibold border border-rldc-teal-primary/40 text-rldc-teal-primary hover:bg-rldc-teal-primary/10"
            >
              {termLoading ? 'Uruchamiam...' : 'Run'}
            </button>
          </div>
          <div className="mt-3 bg-[#060d14] border border-rldc-dark-border rounded p-3 text-xs text-slate-300 min-h-[90px] whitespace-pre-wrap overflow-auto max-h-[220px]">
            {!termOutput && <span className="text-slate-500">Brak wykonania.</span>}
            {termOutput?.error && <span className="text-rldc-red-primary">{termOutput.error}</span>}
            {termOutput && !termOutput.error && (
              <>
                <div className="text-slate-500 mb-1">exit_code={termOutput.exit_code}</div>
                <div>{termOutput.stdout || '(brak stdout)'}</div>
                {!!termOutput.stderr && <div className="text-rldc-red-primary mt-2">{termOutput.stderr}</div>}
              </>
            )}
          </div>
        </div>
      </div>

      <div
        ref={containerRef}
        className="bg-[#060d14] rounded-lg border border-rldc-dark-border font-mono text-xs overflow-y-auto"
        style={{ height: '520px' }}
      >
        {logs.length === 0 && !loading && !error && (
          <div className="p-4 text-slate-500">Brak logów.</div>
        )}
        {[...logs].reverse().map((l: any, idx: number) => (
          <div
            key={l.id ?? idx}
            className="flex gap-2 px-3 py-0.5 border-b border-rldc-dark-border/30 hover:bg-white/[0.02]"
          >
            <span className="text-slate-600 shrink-0 w-[148px]">
              {l.timestamp ? l.timestamp.replace('T', ' ').slice(0, 19) : '--'}
            </span>
            <span className={`w-[60px] shrink-0 font-bold ${levelColor(l.level)}`}>{l.level}</span>
            <span className="text-slate-500 w-[80px] shrink-0 truncate">{l.module}</span>
            <span className="text-slate-300 break-all">{l.message}</span>
            {l.exception && (
              <span className="text-rldc-red-primary/80 ml-1 break-all">{l.exception.slice(0, 120)}</span>
            )}
          </div>
        ))}
      </div>
      <div className="text-[10px] text-slate-600 mt-1">
        {logs.length} wpisów · odświeżanie co 5s{paused ? ' (ZATRZYMANE)' : ''}
      </div>
    </div>
  )
}

/* Panel 2: Aktywność bota */
function DiagActivityTab({ mode }: { mode: 'demo' | 'live' }) {
  const [minutes, setMinutes] = React.useState(15)
  const { data, loading, error, lastUpdated } = useFetch<any>(
    `/api/account/bot-activity?mode=${mode}&minutes=${minutes}`,
    10000
  )
  const d = data?.data || {}
  const actions: any[] = d.last_actions || []
  const positions: any[] = d.open_positions || []

  return (
    <div>
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={10000} />
        <div className="flex gap-1 ml-auto">
          {[5, 15, 30, 60].map(m => (
            <button
              key={m}
              type="button"
              onClick={() => setMinutes(m)}
              className={`px-2 py-0.5 rounded text-[10px] font-bold border transition ${
                minutes === m
                  ? 'bg-rldc-teal-primary/20 text-rldc-teal-primary border-rldc-teal-primary/40'
                  : 'text-slate-400 border-slate-700 hover:text-slate-200'
              }`}
            >
              {m} min
            </button>
          ))}
        </div>
      </div>

      {error && <EmptyState reason="sync-stopped" detail={error} />}

      {/* KPI kafelki */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
        {[
          { label: 'Rozważane symbole', value: d.considered ?? '—', color: 'text-slate-100' },
          { label: 'Odrzucone', value: d.rejected ?? '—', color: 'text-yellow-400' },
          { label: 'Kupione', value: d.bought ?? '—', color: 'text-rldc-green-primary' },
          { label: 'Zamknięte', value: d.closed ?? '—', color: 'text-rldc-red-primary' },
        ].map(tile => (
          <div key={tile.label} className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border">
            <div className="text-xs text-slate-500 mb-1">{tile.label}</div>
            <div className={`text-2xl font-bold ${tile.color}`}>{tile.value}</div>
          </div>
        ))}
      </div>

      {/* Ostatnie akcje */}
      <div className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border mb-4">
        <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-3">Ostatnie akcje bota</div>
        {actions.length === 0 && <div className="text-sm text-slate-500">Brak akcji w tym oknie czasowym.</div>}
        {actions.map((a: any, i: number) => (
          <div key={i} className="flex items-start gap-2 mb-2 text-sm">
            <span className="shrink-0 text-[10px] text-slate-500 w-[140px] mt-0.5">
              {a.ts ? a.ts.replace('T', ' ').slice(0, 19) : '--'}
            </span>
            <span className="text-slate-200">{a.description || `${a.symbol}: ${a.reason_code}`}</span>
          </div>
        ))}
      </div>

      {/* Otwarte pozycje */}
      <div className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border">
        <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-3">
          Otwarte pozycje ({positions.length})
        </div>
        {positions.length === 0 && <div className="text-sm text-slate-500">Brak otwartych pozycji.</div>}
        {positions.map((p: any, i: number) => {
          const pnlPct = p.unrealized_pnl_pct ?? 0
          const pnlColor = pnlPct >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'
          return (
            <div key={p.symbol ?? i} className="flex items-center justify-between py-1.5 border-b border-rldc-dark-border/40 last:border-0">
              <span className="text-sm font-bold text-rldc-teal-primary">{p.symbol}</span>
              <span className="text-xs text-slate-400">wejście: {p.entry_price?.toFixed(4) ?? '—'}</span>
              <span className="text-xs text-slate-300">bieżąca: {p.current_price?.toFixed(4) ?? '—'}</span>
              <span className={`text-xs font-semibold ${pnlColor}`}>
                {pnlPct >= 0 ? '+' : ''}{(pnlPct * 100).toFixed(2)}%
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* Panel 3: Ślad AI — execution-trace */
function DiagTraceTab({ mode }: { mode: 'demo' | 'live' }) {
  const [minutes, setMinutes] = React.useState(30)
  const { data, loading, error, lastUpdated } = useFetch<any>(
    `/api/signals/execution-trace?mode=${mode}&limit_minutes=${minutes}`,
    30000
  )
  const { data: aiStatusData } = useFetch<any>(`/api/account/ai-status`, 60000)
  const items: any[] = data?.data || []

  const aiProviders: any[] = (() => {
    const d = aiStatusData?.data
    if (!d) return []
    const ps = d.providers || {}
    return Object.entries(ps).map(([name, info]: [string, any]) => ({
      name,
      configured: info.configured,
      model: info.model,
      runtime: info.runtime || {},
    }))
  })()
  const activeProvider: string = aiStatusData?.data?.active_provider || '--'

  const reasonColor = (reason: string) => {
    if (!reason) return 'text-slate-400'
    const r = reason.toLowerCase()
    if (r.includes('executed') || r.includes('position_opened') || r.includes('buy')) return 'text-rldc-green-primary'
    if (r.includes('closed') || r.includes('exit') || r.includes('sell')) return 'text-rldc-red-primary'
    if (r.includes('blocked') || r.includes('insufficient') || r.includes('cooldown') || r.includes('gate')) return 'text-yellow-400'
    return 'text-slate-300'
  }

  const providerStatusColor = (status: string) => {
    if (status === 'ok') return 'text-rldc-green-primary border-rldc-green-primary/30 bg-rldc-green-primary/5'
    if (status === 'backoff') return 'text-yellow-400 border-yellow-400/30 bg-yellow-400/5'
    if (status === 'unconfigured') return 'text-slate-500 border-slate-700 bg-slate-800/40'
    return 'text-slate-400 border-slate-700'
  }

  return (
    <div>
      {/* Panel statusu AI Providerów */}
      {aiProviders.length > 0 && (
        <div className="mb-4 bg-rldc-dark-card rounded-lg p-3 border border-rldc-dark-border">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">AI Providers</span>
            <span className="text-[10px] text-slate-500">aktywny:</span>
            <span className="text-[10px] font-bold text-rldc-teal-primary">{activeProvider}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {aiProviders.map((p: any) => {
              const rt = p.runtime || {}
              const status: string = rt.status || (p.configured ? 'ok' : 'unconfigured')
              const label: string = rt.label || (p.configured ? 'aktywny' : 'brak klucza')
              return (
                <div key={p.name} className={`px-2 py-1 rounded border text-[10px] font-mono ${providerStatusColor(status)}`}>
                  <span className="font-bold">{p.name}</span>
                  {p.model && <span className="ml-1 opacity-60">{p.model}</span>}
                  <span className="ml-1.5 opacity-80">· {label}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={30000} />
        <div className="flex gap-1 ml-auto">
          {[15, 30, 60, 120].map(m => (
            <button
              key={m}
              type="button"
              onClick={() => setMinutes(m)}
              className={`px-2 py-0.5 rounded text-[10px] font-bold border transition ${
                minutes === m
                  ? 'bg-rldc-teal-primary/20 text-rldc-teal-primary border-rldc-teal-primary/40'
                  : 'text-slate-400 border-slate-700 hover:text-slate-200'
              }`}
            >
              {m} min
            </button>
          ))}
        </div>
      </div>

      {error && <EmptyState reason="sync-stopped" detail={error} />}

      {items.length === 0 && !loading && !error && (
        <EmptyState reason="no-data" detail="Brak śladów decyzji w tym oknie czasowym." />
      )}

      {items.length > 0 && (
        <div className="space-y-2">
          {items.map((item: any, i: number) => (
            <div
              key={item.symbol ?? i}
              className="bg-rldc-dark-card rounded-lg p-3 border border-rldc-dark-border hover:border-rldc-teal-primary/20 transition"
            >
              <div className="flex items-center justify-between mb-1.5 flex-wrap gap-1">
                <span className="text-sm font-bold text-rldc-teal-primary">{item.symbol}</span>
                <span className={`text-xs font-semibold ${reasonColor(item.reason_code)}`}>
                  {item.reason_code_pl || item.reason_code}
                </span>
                <span className="text-[10px] text-slate-500">
                  {item.timestamp ? item.timestamp.replace('T', ' ').slice(0, 19) : '--'}
                </span>
              </div>
              {item.signal_summary && (
                <div className="text-xs text-slate-400 mb-1">
                  <span className="text-slate-500">Sygnał: </span>{item.signal_summary}
                </div>
              )}
              <div className="flex gap-4 text-[10px] text-slate-500 flex-wrap">
                {item.action_type && <span>Akcja: <span className="text-slate-300">{item.action_type}</span></span>}
                {item.strategy_name && <span>Strategia: <span className="text-slate-300">{item.strategy_name}</span></span>}
                {item.timeframe && <span>TF: <span className="text-slate-300">{item.timeframe}</span></span>}
              </div>
              {item.cost_gate_result && (
                <div className="text-[10px] text-yellow-400/80 mt-1">Koszt: {item.cost_gate_result}</div>
              )}
              {item.risk_gate_result && (
                <div className="text-[10px] text-rldc-red-primary/80 mt-0.5">Ryzyko: {item.risk_gate_result}</div>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="text-[10px] text-slate-600 mt-2">
        {items.length} śladów · odświeżanie co 30s
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Zakładka 4: Status handlu — pipeline + blokery + kapitał
 * ───────────────────────────────────────────────────────────────────────────── */
function DiagTradingTab({ mode }: { mode: 'demo' | 'live' }) {
  const { data: tsRaw, loading, error, lastUpdated } = useFetch<any>(`/api/account/trading-status?mode=${mode}`, 15000)
  const { data: csRaw } = useFetch<any>(`/api/account/capital-snapshot?mode=${mode}`, 20000)
  const ts = tsRaw?.data
  const cs = csRaw?.data

  const severityOrder: Record<string, number> = { critical: 0, warning: 1, info: 2 }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={15000} />
        {ts && (
          <span className={`ml-2 text-xs font-bold px-2 py-0.5 rounded border ${
            ts.status_color === 'green' ? 'text-rldc-green-primary border-rldc-green-primary/40 bg-rldc-green-primary/10' :
            ts.status_color === 'yellow' ? 'text-yellow-400 border-yellow-500/40 bg-yellow-500/10' :
            'text-rldc-red-primary border-rldc-red-primary/40 bg-rldc-red-primary/10'
          }`}>
            {ts.status_color === 'green' ? '● AKTYWNY' : ts.status_color === 'yellow' ? '◐ OGRANICZONY' : '○ ZABLOKOWANY'}
          </span>
        )}
      </div>

      {error && <EmptyState reason="sync-stopped" detail={error} />}

      {ts && (
        <>
          {/* ── Flagi ── */}
          <div className="flex flex-wrap gap-2 mb-5">
            {[
              { label: 'Handel', val: ts.trading_enabled },
              { label: 'Handel live', val: ts.live_trading_enabled },
              { label: 'Binance OK', val: ts.exchange_connected },
              { label: 'WebSocket', val: ts.websocket_enabled },
              { label: 'Kolektor', val: ts.collector_running },
              { label: 'Dane świeże', val: !ts.data_stale },
            ].map(f => (
              <div key={f.label} className={`px-2 py-1 rounded text-[10px] font-bold border ${
                f.val ? 'text-rldc-green-primary border-rldc-green-primary/30 bg-rldc-green-primary/8' :
                'text-rldc-red-primary border-rldc-red-primary/30 bg-rldc-red-primary/8'
              }`}>
                {f.val ? '✓' : '✗'} {f.label}
              </div>
            ))}
          </div>

          {/* ── Blokery ── */}
          {ts.blockers && ts.blockers.length > 0 ? (
            <div className="mb-5">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Aktywne blokery ({ts.blockers.length})</div>
              <div className="space-y-1.5">
                {[...(ts.blockers as any[])].sort((a, b) => (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9)).map((b: any, i: number) => (
                  <div key={i} className={`flex items-start gap-3 px-3 py-2 rounded-lg text-xs border ${
                    b.severity === 'critical' ? 'bg-rldc-red-primary/10 border-rldc-red-primary/30' :
                    b.severity === 'warning'  ? 'bg-yellow-500/10 border-yellow-500/30' :
                    'bg-slate-800 border-slate-700'
                  }`}>
                    <div className="flex-1">
                      <div className="flex items-baseline gap-2">
                        <span className={`font-mono font-bold text-[10px] ${
                          b.severity === 'critical' ? 'text-rldc-red-primary' :
                          b.severity === 'warning'  ? 'text-yellow-400' :
                          'text-slate-400'
                        }`}>{b.code}</span>
                        <span className="text-[10px] text-slate-500">[{b.stage}]</span>
                        {b.symbol && <span className="text-rldc-teal-primary text-[10px]">{b.symbol}</span>}
                      </div>
                      <div className="text-slate-300 mt-0.5">{b.message}</div>
                    </div>
                    {b.timestamp && (
                      <span className="text-[9px] text-slate-600 shrink-0">{String(b.timestamp).replace('T', ' ').slice(0, 16)}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="mb-5 text-xs text-rldc-green-primary bg-rldc-green-primary/8 border border-rldc-green-primary/20 rounded-lg px-3 py-2">
              ✓ Brak aktywnych blokerów — system może handlować
            </div>
          )}

          {/* ── Pipeline 15 min ── */}
          <div className="mb-5">
            <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Pipeline (ostatnie 15 min)</div>
            <div className="flex flex-wrap gap-3">
              {[
                { label: 'Kandydatów', value: ts.candidate_count, c: 'text-slate-300' },
                { label: 'Kupiono', value: ts.bought_count_15m, c: 'text-rldc-green-primary' },
                { label: 'Zamknięto', value: ts.closed_count_15m, c: 'text-rldc-red-primary' },
                { label: 'Pominięto', value: ts.skipped_count_15m, c: 'text-yellow-400' },
              ].map(s => (
                <div key={s.label} className="terminal-card rounded-lg px-4 py-3 border border-rldc-dark-border min-w-[80px] text-center">
                  <div className="text-[9px] text-slate-500 uppercase tracking-widest">{s.label}</div>
                  <div className={`text-xl font-bold font-mono mt-1 ${s.c}`}>{s.value ?? '--'}</div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Ostatnia decyzja ── */}
          {(ts.last_decision_time || ts.last_rejection_reason || ts.last_order_error) && (
            <div className="mb-5 terminal-card rounded-lg border border-rldc-dark-border px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Ostatnia aktywność decyzyjna</div>
              <div className="space-y-1 text-xs">
                {ts.last_decision_time && (
                  <div className="flex gap-2">
                    <span className="text-slate-500 w-28 shrink-0">Czas decyzji:</span>
                    <span className="text-slate-300">{String(ts.last_decision_time).replace('T', ' ').slice(0, 19)}</span>
                  </div>
                )}
                {ts.last_attempted_symbol && (
                  <div className="flex gap-2">
                    <span className="text-slate-500 w-28 shrink-0">Symbol:</span>
                    <span className="text-rldc-teal-primary font-mono">{ts.last_attempted_symbol}</span>
                  </div>
                )}
                {ts.last_rejection_reason && (
                  <div className="flex gap-2">
                    <span className="text-slate-500 w-28 shrink-0">Przyczyna odrzucenia:</span>
                    <span className="text-yellow-400">{ts.last_rejection_reason}</span>
                  </div>
                )}
                {ts.last_order_error && (
                  <div className="flex gap-2">
                    <span className="text-slate-500 w-28 shrink-0">Błąd zlecenia:</span>
                    <span className="text-rldc-red-primary">{ts.last_order_error}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Snapshot kapitału ── */}
      {cs && (
        <div className="terminal-card rounded-lg border border-rldc-dark-border px-4 py-3">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">Snapshot kapitału</div>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-xs">
            {[
              { label: 'Łączna wartość', value: cs.total_account_value != null ? `${Number(cs.total_account_value).toFixed(2)} ${cs.base_currency}` : '--', c: 'text-rldc-green-primary font-bold' },
              { label: 'Wolne środki', value: cs.free_cash != null ? `${Number(cs.free_cash).toFixed(2)} ${cs.base_currency}` : '--', c: 'text-slate-100' },
              { label: 'W pozycjach', value: cs.active_positions_value != null ? `${Number(cs.active_positions_value).toFixed(2)} ${cs.base_currency}` : '--', c: 'text-slate-100' },
              { label: 'Wartość pyłu', value: cs.dust_value != null ? `${Number(cs.dust_value).toFixed(4)} ${cs.base_currency}` : '--', c: 'text-slate-500' },
              { label: 'Aktywne pozycje', value: cs.active_positions_count ?? '--', c: 'text-slate-300' },
              { label: 'Pył', value: cs.dust_positions_count ?? '--', c: 'text-slate-500' },
              { label: 'Gotówka', value: cs.cash_assets_count ?? '--', c: 'text-slate-300' },
              { label: 'Wszystkie aktywa', value: cs.all_assets_count ?? '--', c: 'text-slate-300' },
            ].map(r => (
              <div key={r.label} className="flex gap-2 items-baseline">
                <span className="text-slate-600 w-32 shrink-0">{r.label}:</span>
                <span className={r.c}>{String(r.value)}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-rldc-dark-border/50 flex flex-wrap gap-3 text-[10px]">
            <span className="text-slate-500">Źródło: <span className="text-slate-300">{cs.source_of_truth}</span></span>
            <span className="text-slate-500">Sync: {cs.sync_status === 'ok' ? <span className="text-rldc-green-primary">OK</span> : <span className="text-yellow-400">{cs.sync_status}</span>}</span>
            {cs.stale && <span className="text-yellow-400">⚠ Dane mogą być nieaktualne ({cs.age_seconds}s temu)</span>}
            {cs.sync_warning && <span className="text-yellow-400">⚠ {cs.sync_warning}</span>}
          </div>
        </div>
      )}
    </div>
  )
}

function BlogView() {
  const { data, loading, error } = useFetch<any>(`/api/blog/list?limit=10`, 60000)
  const rows = (data?.data || []).map((p: any) => [
    p.title,
    p.status,
    p.created_at,
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Blog" description="Wpisy z analizy rynku i historia ważnych zdarzeń." />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <SimpleTable
        title="Wpisy blogowe"
        headers={['Tytuł', 'Status', 'Utworzono']}
        rows={rows}
      />
    </div>
  )
}


/* ─────────────────────────────────────────────────
 *  WIDOK: Analiza pozycji — karty decyzyjne
/* ─────────────────────────────────────────────────
 *  WIDOK: Raporty Makro — analytics overview
 * ───────────────────────────────────────────────── */
function MacroReportsView({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading, error, lastUpdated } = useFetch<any>(`/api/account/analytics/overview?mode=${mode}`, 60000)
  const { data: botData } = useFetch<any>('/api/account/bot-activity', 30000)
  const d = data?.data || {}
  const r = d.risk_snapshot || {}
  const bot = botData?.data || {}
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Raporty Makro" description="Przegląd ogólny wydajności, aktywność bota i status ryzyka." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={60000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {!loading && !error && (
        <div className="space-y-6">
          {/* Bot Activity */}
          <div className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border">
            <div className="text-xs font-semibold text-slate-300 mb-3">Aktywność bota (ostatnie {bot.window_minutes || 15} min)</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: 'Rozważone', val: bot.considered ?? 0, color: 'text-slate-200' },
                { label: 'Odrzucone', val: bot.rejected ?? 0, color: 'text-amber-400' },
                { label: 'Kupione', val: bot.bought ?? 0, color: 'text-rldc-green-primary' },
                { label: 'Zamknięte', val: bot.closed ?? 0, color: 'text-rldc-red-primary' },
              ].map(k => (
                <div key={k.label} className="text-center">
                  <div className="text-[10px] text-slate-500 uppercase">{k.label}</div>
                  <div className={`text-xl font-bold font-mono ${k.color}`}>{k.val}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Ostatnie akcje bota */}
          {(bot.last_actions || []).length > 0 && (
            <div className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border">
              <div className="text-xs font-semibold text-slate-300 mb-3">Ostatnie decyzje bota</div>
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {(bot.last_actions || []).slice(0, 15).map((a: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-xs py-1 border-b border-rldc-dark-border/40">
                    <span className={`font-bold w-14 ${a.action_type === 'skip' ? 'text-slate-500' : a.action_type === 'buy' ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>{(a.action_type || '').toUpperCase()}</span>
                    <span className="text-rldc-teal-primary font-mono w-20">{a.symbol}</span>
                    <span className="text-slate-400 flex-1 truncate">{a.description}</span>
                    <span className="text-[10px] text-slate-500">{(a.ts || '').slice(11, 19)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Risk snapshot */}
          <div className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border">
            <div className="text-xs font-semibold text-slate-300 mb-3">Snapshot ryzyka</div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {[
                { label: 'Drawdown dzienny netto', val: `${(r.daily_net_drawdown ?? 0).toFixed(2)} EUR` },
                { label: 'Loss streak', val: String(r.loss_streak_net ?? 0) },
                { label: 'Ekspozycja łączna', val: `${(r.total_exposure ?? 0).toFixed(2)} EUR` },
                { label: 'Aktywacje cooldown', val: String(d.cooldown_activations ?? 0) },
                { label: 'Kill switch', val: r.kill_switch_triggered ? '🔴 TAK' : '🟢 NIE' },
                { label: 'Cost leakage ratio', val: `${((d.cost_leakage_ratio ?? 0) * 100).toFixed(1)}%` },
              ].map(k => (
                <div key={k.label} className="py-1.5">
                  <div className="text-[10px] text-slate-500 uppercase">{k.label}</div>
                  <div className="text-sm font-mono text-slate-200">{k.val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────
 *  WIDOK: Statystyki i Raporty — trading effectiveness
 * ───────────────────────────────────────────────── */
function ReportsView({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading, error, lastUpdated } = useFetch<any>(`/api/account/analytics/trading-effectiveness?mode=${mode}`, 60000)
  const { data: statsData } = useFetch<any>(`/api/orders/stats?mode=${mode}&days=30`, 60000)
  const s = data?.data?.summary || {}
  const bySymbol = data?.data?.by_symbol || []
  const stats = statsData?.data || {}
  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center justify-between mb-5">
        <ViewHeader title="Statystyki i Raporty" description="Efektywność tradingu, wyniki wg symboli i koszty." />
        <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={60000} />
      </div>
      {error && <EmptyState reason="sync-stopped" detail={error} />}
      {!loading && !error && (
        <div className="space-y-6">
          {/* KPI Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: 'Zamknięte trade\'y', val: String(s.closed_trades ?? 0), color: 'text-slate-200' },
              { label: 'Zleceń łącznie', val: String(stats.total ?? s.total_orders ?? 0), color: 'text-slate-200' },
              { label: 'Win rate netto', val: `${((s.win_rate_net ?? 0) * 100).toFixed(1)}%`, color: (s.win_rate_net ?? 0) >= 0.5 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
              { label: 'Zysk netto', val: `${(s.net_pnl ?? 0).toFixed(2)} EUR`, color: (s.net_pnl ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
              { label: 'Expectancy', val: `${(s.net_expectancy ?? 0).toFixed(4)} EUR`, color: (s.net_expectancy ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary' },
              { label: 'Koszty łączne', val: `${(s.total_cost ?? 0).toFixed(2)} EUR`, color: 'text-amber-400' },
              { label: 'Wskaźnik wykonania', val: `${(stats.fill_rate ?? 0).toFixed(0)}%`, color: 'text-slate-200' },
              { label: 'Werdykt', val: s.verdict || '--', color: s.verdict === 'zyskowny' ? 'text-rldc-green-primary' : s.verdict === 'stratny' ? 'text-rldc-red-primary' : 'text-amber-400' },
            ].map(k => (
              <div key={k.label} className="bg-rldc-dark-card rounded-lg p-3 border border-rldc-dark-border">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">{k.label}</div>
                <div className={`text-lg font-bold font-mono mt-1 ${k.color}`}>{k.val}</div>
              </div>
            ))}
          </div>
          {s.verdict_reason && (
            <div className="bg-rldc-dark-card rounded-lg p-3 border border-rldc-dark-border text-xs text-slate-400">
              <span className="font-semibold text-slate-300">Uzasadnienie: </span>{s.verdict_reason}
            </div>
          )}

          {/* Per-symbol breakdown */}
          {bySymbol.length > 0 && (
            <div className="bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border">
              <div className="text-xs font-semibold text-slate-300 mb-3">Wyniki wg symboli</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[10px] text-slate-500 uppercase border-b border-rldc-dark-border">
                      <th className="text-left py-2 px-2">Symbol</th>
                      <th className="text-right py-2 px-2">Trade&apos;y</th>
                      <th className="text-right py-2 px-2">Zysk netto</th>
                      <th className="text-right py-2 px-2">Win rate</th>
                      <th className="text-right py-2 px-2">Expectancy</th>
                      <th className="text-right py-2 px-2">Koszty</th>
                      <th className="text-right py-2 px-2">Werdykt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bySymbol.map((r: any) => (
                      <tr key={r.symbol} className="border-b border-rldc-dark-border/40 hover:bg-white/[0.02]">
                        <td className="py-2 px-2 font-mono text-rldc-teal-primary font-bold">{r.symbol}</td>
                        <td className="py-2 px-2 text-right text-slate-300">{r.closed_trades}</td>
                        <td className={`py-2 px-2 text-right font-mono ${(r.net_pnl ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>{(r.net_pnl ?? 0).toFixed(3)}</td>
                        <td className="py-2 px-2 text-right text-slate-300">{((r.win_rate_net ?? 0) * 100).toFixed(0)}%</td>
                        <td className={`py-2 px-2 text-right font-mono ${(r.net_expectancy ?? 0) >= 0 ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}`}>{(r.net_expectancy ?? 0).toFixed(4)}</td>
                        <td className="py-2 px-2 text-right text-amber-400 font-mono">{(r.total_cost ?? 0).toFixed(3)}</td>
                        <td className={`py-2 px-2 text-right ${r.verdict === 'zyskowny' ? 'text-rldc-green-primary' : r.verdict === 'stratny' ? 'text-rldc-red-primary' : 'text-amber-400'}`}>{r.verdict || '--'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function signalLabel(type: string): string {
  const map: Record<string, string> = {
    BUY: 'Kupno', SELL: 'Sprzedaż', HOLD: 'Trzymaj',
    STRONG_BUY: 'Silne kupno', STRONG_SELL: 'Silna sprzedaż',
    NEUTRAL: 'Neutralny', WAIT: 'Czekaj',
  }
  return map[String(type || '').toUpperCase()] || String(type || '--')
}

function decisionColor(d: string) {
  if (d === 'SPRZEDAJ') return 'text-rldc-red-primary'
  if (d === 'TRZYMAJ') return 'text-rldc-green-primary'
  if (d === 'DUST') return 'text-slate-500'
  if (d === 'BRAK DANYCH') return 'text-yellow-500'
  return 'text-rldc-orange-primary'
}

function decisionBg(d: string) {
  if (d === 'SPRZEDAJ') return 'bg-rldc-red-primary/10 border-rldc-red-primary/30'
  if (d === 'TRZYMAJ') return 'bg-rldc-green-primary/10 border-rldc-green-primary/30'
  if (d === 'DUST') return 'bg-slate-700/20 border-slate-600/30'
  if (d === 'BRAK DANYCH') return 'bg-yellow-500/5 border-yellow-500/20'
  return 'bg-rldc-orange-primary/10 border-rldc-orange-primary/30'
}

function pnlColor(v: number) {
  if (v > 0) return 'text-rldc-green-primary'
  if (v < 0) return 'text-rldc-red-primary'
  return 'text-slate-300'
}

function PositionAnalysisView({ mode, onSymbolClick }: { mode: 'demo' | 'live'; onSymbolClick?: (s: string) => void }) {
  const { data, loading, error, lastUpdated } = useFetch<any>(
    `/api/positions/analysis?mode=${mode}`,
    30000
  )
  const [goals, setGoals] = useState<Record<string, any>>({})
  const [goalInput, setGoalInput] = useState<Record<string, string>>({})
  const [goalEdit, setGoalEdit] = useState<string | null>(null)

  useEffect(() => {
    // Ładuj cele z API (z fallback na localStorage dla szybkości)
    setGoals(loadGoals())
    // Odśwież każdy goal z backendu asynchronicznie
    fetch(`${getApiBase()}/api/positions?mode=${mode}`)
      .then(r => r.json())
      .catch(() => null)
      .then(res => {
        const symbols: string[] = (res?.data || []).map((p: any) => p.symbol).filter(Boolean)
        symbols.forEach(sym => {
          fetch(`${getApiBase()}/api/positions/goal/${sym}`)
            .then(r => r.json())
            .then(json => {
              if (json.goal) {
                const g = { targetEur: json.goal.target_eur, setAt: json.goal.set_at || new Date().toISOString() }
                saveGoal(sym, g)
                setGoals(prev => ({ ...prev, [sym]: g }))
              }
            })
            .catch(() => null)
        })
      })
  }, [mode])

  const handleSaveGoal = (symbol: string) => {
    const raw = goalInput[symbol] || ''
    const val = parseFloat(raw.replace(',', '.'))
    if (!Number.isFinite(val) || val <= 0) return
    const g: any = { targetEur: val, setAt: new Date().toISOString() }
    // Zapis do backendu
    fetch(`${getApiBase()}/api/positions/goal/${symbol}`, {
      method: 'PUT',
      headers: withAdminToken({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ target_eur: val }),
    }).catch(() => null)
    // Zapis do localStorage jako cache
    saveGoal(symbol, g)
    setGoals((prev) => ({ ...prev, [symbol]: g }))
    setGoalEdit(null)
  }

  const cards: any[] = data?.data || []
  const summary = data?.summary || {}

  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="mb-5">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Co mam i co z tym zrobić?</h1>
          <div className="flex items-center gap-3">
            <DataStatus lastUpdated={lastUpdated} loading={loading} error={error} refreshMs={30000} />
            <div className="px-3 py-1 bg-rldc-teal-primary/20 text-rldc-teal-primary rounded text-sm font-medium">
              Tryb: {mode.toUpperCase()}
            </div>
          </div>
        </div>
        <p className="text-sm text-slate-400 mt-1">Analiza każdej pozycji — decyzja systemu, powody i zalecane działanie.</p>
      </div>

      {loading && !data && <div className="text-sm text-slate-400 mb-4">Ładowanie analizy…</div>}
      {error && <EmptyState reason="sync-stopped" detail={error} />}

      {/* Podsumowanie */}
      {summary.positions_count !== undefined && (
        <>
          {/* Ostrzeżenie gdy brak pełnych pozycji */}
          {summary.valid_positions_count === 0 && summary.positions_count > 0 && (
            <div className="mb-4 px-4 py-3 rounded-lg border border-yellow-500/30 bg-yellow-500/10 text-yellow-300 text-sm">
              Brak pełnych pozycji tradingowych do analizy. Widoczne są jedynie resztki aktywów
              {summary.missing_entry_count > 0 && ` lub pozycje bez historii wejścia (${summary.missing_entry_count})`}.
            </div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Aktywne pozycje</div>
              <div className="text-xl font-bold text-slate-100 mt-1">{summary.valid_positions_count ?? summary.positions_count}</div>
              {(summary.dust_positions_count > 0 || summary.missing_entry_count > 0) && (
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {summary.dust_positions_count > 0 && `+${summary.dust_positions_count} pył`}
                  {summary.dust_positions_count > 0 && summary.missing_entry_count > 0 && ', '}
                  {summary.missing_entry_count > 0 && `+${summary.missing_entry_count} bez wejścia`}
                </div>
              )}
            </div>
            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Wartość aktywnych</div>
              <div className="text-xl font-bold text-slate-100 mt-1">
                {summary.total_value_eur != null && summary.total_value_eur > 0
                  ? `${summary.total_value_eur.toFixed(2)} EUR`
                  : summary.all_assets_value_eur != null
                    ? <span className="text-slate-400">{summary.all_assets_value_eur.toFixed(2)} EUR</span>
                    : '--'}
              </div>
              {summary.total_value_eur === 0 && summary.dust_value_eur != null && (
                <div className="text-[10px] text-slate-500 mt-0.5">pył: {summary.dust_value_eur.toFixed(4)} EUR</div>
              )}
            </div>
            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Zainwestowano</div>
              <div className="text-xl font-bold text-slate-100 mt-1">
                {summary.total_cost_eur != null
                  ? `${summary.total_cost_eur.toFixed(2)} EUR`
                  : <span className="text-slate-500 text-sm">brak potwierdzonych danych</span>}
              </div>
            </div>
            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Łączny wynik</div>
              <div className={`text-xl font-bold mt-1 ${summary.total_pnl_eur != null ? pnlColor(summary.total_pnl_eur) : 'text-slate-500'}`}>
                {summary.total_pnl_eur != null
                  ? `${summary.total_pnl_eur >= 0 ? '+' : ''}${summary.total_pnl_eur.toFixed(2)} EUR`
                  : <span className="text-sm">brak danych</span>}
              </div>
            </div>
            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3 neon-card">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Wynik %</div>
              <div className={`text-xl font-bold mt-1 ${summary.total_pnl_pct != null && summary.total_pnl_pct !== 0 ? pnlColor(summary.total_pnl_pct) : 'text-slate-500'}`}>
                {summary.total_pnl_pct != null && summary.total_cost_eur != null
                  ? `${summary.total_pnl_pct >= 0 ? '+' : ''}${summary.total_pnl_pct.toFixed(2)}%`
                  : <span className="text-sm">brak danych</span>}
              </div>
            </div>
          </div>
        </>
      )}

      {cards.length === 0 && !loading && !error && (
        <EmptyState reason="no-data" detail="Brak otwartych pozycji do analizy." />
      )}

      <div className="space-y-4">
        {cards.map((c: any) => {
          const goal = goals[c.symbol]
          const posValue = typeof c.position_value_eur === 'number' ? c.position_value_eur : null
          const goalRemaining = goal && posValue !== null ? goal.targetEur - posValue : null
          const pctNeeded = goal && posValue !== null && posValue > 0
            ? ((goal.targetEur - posValue) / posValue) * 100
            : null
          const realism = pctNeeded !== null ? assessGoalRealism(pctNeeded, c.trend, c.rsi) : null

          // Klasyfikacja wizualna na podstawie pól z backendu
          const isDust = c.is_dust === true || c.classification === 'dust_position'
          const isMissingEntry = !isDust && c.classification === 'missing_entry_price'
          const isValid = c.classification === 'valid_position'

          // Style karty wg klasyfikacji
          const cardBorderClass = isDust
            ? 'border-slate-700/40 opacity-60'
            : isMissingEntry
              ? 'border-yellow-500/30'
              : 'border-rldc-dark-border'

          return (
            <div
              key={c.symbol}
              className={`bg-rldc-dark-card rounded-lg border neon-card overflow-hidden ${cardBorderClass}`}
            >
              {/* Nagłówek karty */}
              <div className="flex items-center justify-between px-5 py-3 border-b border-rldc-dark-border/50">
                <div className="flex items-center gap-3">
                  <span
                    className={`text-lg font-bold cursor-pointer hover:underline ${isDust ? 'text-slate-400' : 'text-rldc-teal-primary'}`}
                    onClick={() => onSymbolClick?.(c.symbol)}
                    title="Kliknij aby otworzyć panel szczegółów"
                  >
                    {c.symbol}
                  </span>
                  {c.is_hold && (
                    <span className="px-2 py-0.5 rounded bg-rldc-orange-primary/20 text-rldc-orange-primary text-[10px] font-semibold border border-rldc-orange-primary/30">
                      HOLD
                    </span>
                  )}
                  {/* Badge klasyfikacji */}
                  {isDust && (
                    <span className="px-2 py-0.5 rounded bg-slate-700/40 text-slate-400 text-[10px] font-semibold border border-slate-600/40">
                      PYŁ
                    </span>
                  )}
                  {isMissingEntry && (
                    <span className="px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-400 text-[10px] font-semibold border border-yellow-500/30">
                      BRAK DANYCH WEJŚCIA
                    </span>
                  )}
                  {isValid && c.source === 'binance_spot' && (
                    <span className="px-2 py-0.5 rounded bg-rldc-teal-primary/20 text-rldc-teal-primary text-[10px] font-semibold border border-rldc-teal-primary/30">
                      LIVE Spot
                    </span>
                  )}
                  {isValid && c.source !== 'binance_spot' && (
                    <span className="px-2 py-0.5 rounded bg-rldc-green-primary/20 text-rldc-green-primary text-[10px] font-semibold border border-rldc-green-primary/30">
                      AKTYWNA POZYCJA
                    </span>
                  )}
                  <span className="text-xs text-slate-500">
                    {c.side} • {c.opened_at ? `otwarcie ${c.opened_at.slice(0, 10)}` : c.source === 'binance_spot' || c.source === 'binance_spot_dust' ? 'Binance' : '--'}
                  </span>
                </div>
                {/* Badge decyzji — TYLKO dla valid_position */}
                {isValid ? (
                  <div className={`px-4 py-1.5 rounded-lg border text-sm font-bold ${decisionBg(c.decision)}`}>
                    <span className={decisionColor(c.decision)}>{c.decision}</span>
                    {c.strength && c.strength !== 'NEUTRALNY' && (
                      <span className="text-[10px] text-slate-400 ml-2">({c.strength})</span>
                    )}
                  </div>
                ) : isDust ? (
                  <div className="px-4 py-1.5 rounded-lg border border-slate-600/40 bg-slate-700/20 text-sm font-bold text-slate-400">
                    PYŁ
                  </div>
                ) : (
                  <div className="px-4 py-1.5 rounded-lg border border-yellow-500/30 bg-yellow-500/10 text-sm font-bold text-yellow-400">
                    BRAK DANYCH
                  </div>
                )}
              </div>

              {/* Baner ostrzegawczy dla pozycji bez danych */}
              {c.warning_message && (
                <div className={`px-5 py-2 text-xs flex items-center gap-2 ${isDust ? 'bg-slate-800/40 text-slate-500' : 'bg-yellow-500/10 text-yellow-300 border-b border-yellow-500/20'}`}>
                  <span>{isDust ? 'ℹ' : '⚠'}</span>
                  <span>{c.warning_message}</span>
                </div>
              )}

              {/* Zawartość karty */}
              <div className={`px-5 py-4 ${isDust ? 'opacity-70' : ''}`}>
                {/* Wiersz 1: ceny i P&L */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-4">
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Ilość</div>
                    <div className="text-sm font-mono text-slate-200">{typeof c.quantity === 'number' ? (c.quantity < 0.01 ? c.quantity.toFixed(8) : c.quantity) : c.quantity}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Kupiono po</div>
                    {c.has_entry_price
                      ? <div className="text-sm font-mono text-slate-200">{c.entry_price < 0.0001 ? c.entry_price.toFixed(8) : c.entry_price > 10 ? c.entry_price.toFixed(2) : c.entry_price.toFixed(6)} EUR</div>
                      : <div className="text-sm font-mono text-amber-500/80 italic">nieznana</div>
                    }
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Teraz</div>
                    <div className="text-sm font-mono text-slate-200">{c.current_price != null ? `${c.current_price < 0.0001 ? c.current_price.toFixed(8) : c.current_price > 10 ? c.current_price.toFixed(2) : c.current_price.toFixed(6)} EUR` : '--'}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Wartość pozycji</div>
                    <div className="text-sm font-mono text-slate-200">{posValue != null ? `${posValue.toFixed(posValue < 1 ? 6 : 2)} EUR` : '--'}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Wynik (EUR)</div>
                    {c.can_compute_pnl && c.pnl_eur != null
                      ? <div className={`text-sm font-mono font-bold ${pnlColor(c.pnl_eur)}`}>{c.pnl_eur >= 0 ? '+' : ''}{c.pnl_eur.toFixed(4)} EUR</div>
                      : <div className="text-sm font-mono text-slate-600 italic">—</div>
                    }
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Wynik (%)</div>
                    {c.can_compute_pnl && c.pnl_pct != null
                      ? <div className={`text-sm font-mono font-bold ${pnlColor(c.pnl_pct)}`}>{c.pnl_pct >= 0 ? '+' : ''}{c.pnl_pct.toFixed(2)}%</div>
                      : <div className="text-sm font-mono text-slate-600 italic">—</div>
                    }
                  </div>
                </div>

                {/* Sekcja analizy technicznej — tylko dla valid_position */}
                {isValid && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <div>
                      <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Trend</div>
                      <div className={`text-sm font-semibold ${c.trend === 'WZROSTOWY' ? 'text-rldc-green-primary' : c.trend === 'SPADKOWY' ? 'text-rldc-red-primary' : 'text-slate-400'}`}>
                        {c.trend === 'WZROSTOWY' ? '▲ Wzrostowy' : c.trend === 'SPADKOWY' ? '▼ Spadkowy' : '— Brak danych'}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">RSI (moc rynku)</div>
                      <div className={`text-sm font-mono ${c.rsi !== null ? (c.rsi < 30 ? 'text-rldc-green-primary' : c.rsi > 70 ? 'text-rldc-red-primary' : 'text-slate-200') : 'text-slate-500'}`}>
                        {c.rsi !== null ? `${c.rsi}${c.rsi < 30 ? ' (wyprzedany)' : c.rsi > 70 ? ' (wykupiony)' : ''}` : '--'}
                      </div>
                    </div>
                    {c.planned_tp !== null && (
                      <div>
                        <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Cel zysku (TP)</div>
                        <div className="text-sm font-mono text-rldc-green-primary">{c.planned_tp?.toFixed(c.planned_tp > 10 ? 2 : 6)}</div>
                      </div>
                    )}
                    {c.planned_sl !== null && (
                      <div>
                        <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Ochrona straty (SL)</div>
                        <div className="text-sm font-mono text-rldc-red-primary">{c.planned_sl?.toFixed(c.planned_sl > 10 ? 2 : 6)}</div>
                      </div>
                    )}
                    {c.is_hold && c.hold_target_eur !== undefined && (
                      <div>
                        <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Cel wyceny (HOLD)</div>
                        <div className="text-sm font-mono text-rldc-orange-primary">
                          {c.hold_target_eur} EUR
                          {typeof c.hold_remaining_eur === 'number' && (
                            <span className="text-[10px] text-slate-400 ml-1">(brakuje {c.hold_remaining_eur.toFixed(2)} EUR)</span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Sekcja celu użytkownika — tylko gdy można liczyć wartość */}
                {!isDust && (
                  <div className="bg-[#0b121a] rounded-lg border border-rldc-dark-border/40 px-4 py-3 mb-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-[10px] uppercase tracking-widest text-slate-500">Twój cel wartości pozycji (EUR)</div>
                      <button
                        onClick={() => setGoalEdit(goalEdit === c.symbol ? null : c.symbol)}
                        className="text-[10px] text-rldc-teal-primary hover:underline"
                      >
                        {goal ? 'Zmień' : 'Ustaw cel'}
                      </button>
                    </div>
                    {goalEdit === c.symbol && (
                      <div className="flex items-center gap-2 mb-2">
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          placeholder="np. 300"
                          value={goalInput[c.symbol] || ''}
                          onChange={(e) => setGoalInput((p) => ({ ...p, [c.symbol]: e.target.value }))}
                          className="w-28 px-2 py-1 text-xs rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 font-mono"
                        />
                        <button
                          onClick={() => handleSaveGoal(c.symbol)}
                          className="px-3 py-1 text-[10px] rounded bg-rldc-teal-primary/20 text-rldc-teal-primary hover:bg-rldc-teal-primary/30 transition"
                        >
                          Zapisz
                        </button>
                        {goal && (
                          <button
                            onClick={() => {
                              fetch(`${getApiBase()}/api/positions/goal/${c.symbol}`, {
                                method: 'DELETE',
                                headers: withAdminToken(),
                              }).catch(() => null)
                              removeGoal(c.symbol)
                              setGoals((p) => { const n = { ...p }; delete n[c.symbol]; return n })
                              setGoalEdit(null)
                            }}
                            className="px-3 py-1 text-[10px] rounded bg-slate-500/10 text-slate-400 hover:bg-slate-500/20 transition"
                          >
                            Usuń
                          </button>
                        )}
                      </div>
                    )}
                    {goal ? (
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-4 flex-wrap text-sm">
                          <span className="text-slate-300">Cel: <span className="font-mono font-bold text-slate-100">{goal.targetEur} EUR</span></span>
                          {goalRemaining !== null && (
                            <span className={`font-mono font-bold ${goalRemaining <= 0 ? 'text-rldc-green-primary' : 'text-yellow-400'}`}>
                              {goalRemaining <= 0 ? '✓ Cel osiągnięty!' : `Brakuje: ${goalRemaining.toFixed(2)} EUR`}
                            </span>
                          )}
                          {pctNeeded !== null && goalRemaining !== null && goalRemaining > 0 && (
                            <span className="text-slate-400 text-xs">
                              Potrzebny ruch: <span className="font-mono font-semibold text-slate-200">{pctNeeded > 0 ? '+' : ''}{pctNeeded.toFixed(1)}%</span>
                            </span>
                          )}
                        </div>
                        {realism && goalRemaining !== null && goalRemaining > 0 && (
                          <div className="flex items-center gap-2 text-xs">
                            <span className="text-slate-500">Ocena celu:</span>
                            <span className={`font-semibold ${realism.color}`}>{realism.label}</span>
                            <span className="text-slate-500">— {realism.explanation}</span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-xs text-slate-500">Nie ustawiono celu. Kliknij „Ustaw cel" aby śledzić dystans do wartości docelowej.</div>
                    )}
                  </div>
                )}

                {/* Powody decyzji */}
                <div className={`rounded-lg border px-4 py-3 ${isMissingEntry ? 'bg-yellow-500/5 border-yellow-500/20' : 'bg-[#0b121a] border-rldc-dark-border/50'}`}>
                  <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">
                    {isValid ? 'Dlaczego system tak uważa' : 'Informacja o pozycji'}
                  </div>
                  <ul className="space-y-1">
                    {(c.reasons || []).map((r: string, i: number) => (
                      <li key={i} className={`text-sm flex items-start gap-2 ${isMissingEntry ? 'text-yellow-200/80' : isDust ? 'text-slate-500' : 'text-slate-300'}`}>
                        <span className={`mt-0.5 ${isMissingEntry ? 'text-yellow-500' : isDust ? 'text-slate-600' : 'text-rldc-teal-primary'}`}>•</span>
                        <span>{r}</span>
                      </li>
                    ))}
                    {(!c.reasons || c.reasons.length === 0) && (
                      <li className="text-sm text-slate-500">Brak dodatkowych informacji</li>
                    )}
                  </ul>
                </div>

                {/* Co zrobić? — TYLKO dla valid_position */}
                {isValid && (
                  <div className={`mt-3 rounded-lg border px-4 py-3 ${decisionBg(c.decision)}`}>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Co teraz zrobić?</div>
                    <p className={`text-sm font-medium ${decisionColor(c.decision)}`}>
                      {c.decision === 'TRZYMAJ'
                        ? 'Nic nie rób. System uważa, że warto jeszcze poczekać — pozycja ma potencjał wzrostu.'
                        : c.decision === 'SPRZEDAJ'
                          ? 'Rozważ zamknięcie pozycji. System widzi dobry moment realizacji zysku lub chce ograniczyć ryzyko.'
                          : c.decision === 'REDUKUJ'
                            ? 'Rozważ częściowe wyjście. System widzi sygnały, że część zysku warto zabezpieczyć.'
                            : 'Obserwuj sytuację. System nie widzi jeszcze wyraźnego sygnału — poczekaj na potwierdzenie.'}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SettingsView({ activeView, mode }: { activeView: string, mode: 'demo' | 'live' }) {
  const isLogs = activeView === 'logs'
  const title = isLogs ? 'Logi — ostatnie działania' : 'Ustawienia'
  const description = isLogs
    ? 'Co system ostatnio zrobił — zdarzenia, decyzje, błędy.'
    : 'Konfiguracja bota — włącz/wyłącz trading, ustaw listę obserwowanych par.'
  const { data, loading, error } = useFetch<any>(`/api/portfolio/wealth?mode=${mode}`, isLogs ? 60000 : 0)
  const [controlRefreshKey, setControlRefreshKey] = useState(0)
  const { data: controlState } = useFetch<any>(
    `/api/control/state?rk=${controlRefreshKey}`,
    isLogs ? 0 : 15000
  )
  const { data: logsData, loading: logsLoading, error: logsError } = useFetch<any>(
    isLogs ? `/api/account/system-logs?limit=80` : '',
    isLogs ? 60000 : 0
  )
  const [resetStatus, setResetStatus] = useState<string | null>(null)
  const [adminToken, setAdminToken] = useState<string>('')
  const [controlStatus, setControlStatus] = useState<string | null>(null)
  const [watchlistOverrideInput, setWatchlistOverrideInput] = useState<string>('')
  const [holdStatus, setHoldStatus] = useState<string | null>(null)

  useEffect(() => {
    setAdminToken(getAdminToken())
  }, [])

  useEffect(() => {
    const s = controlState?.data
    if (!s) return
    const override = Array.isArray(s.watchlist_override) ? s.watchlist_override : null
    if (override && override.length) {
      setWatchlistOverrideInput(String(override.join(',')))
    }
  }, [controlState?.data])

  const normalizeWatchlist = (raw: string): string[] => {
    const items = String(raw || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => s.replace(/\s+/g, '').replaceAll('/', '').replaceAll('-', '').toUpperCase())
      .filter(Boolean)
    return Array.from(new Set(items))
  }

  const postControl = async (payload: any) => {
    setControlStatus('Zapisuję...')
    try {
      const headers: Record<string, string> = withAdminToken({ 'Content-Type': 'application/json' })
      const res = await fetch(`${getApiBase()}/api/control/state`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const msg = res.status === 401 ? '401 Unauthorized (ADMIN_TOKEN?)' : 'Błąd zapisu'
        throw new Error(msg)
      }
      setControlStatus('OK')
      setControlRefreshKey((k) => k + 1)
    } catch (e: any) {
      setControlStatus(String(e?.message || 'Błąd zapisu'))
    }
  }

  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title={title} description={description} />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
        <h2 className="text-lg font-semibold mb-4 text-slate-200">Podstawowe dane konta</h2>
        <div className="text-sm text-slate-400">
          Wartość konta: {data?.total_equity?.toFixed(2) || '--'} EUR &nbsp;|&nbsp; Saldo: {data?.balance?.toFixed(2) || '--'} EUR
        </div>
        <div className="mt-4">
          <div className="text-xs text-slate-500 mb-2">Admin token (opcjonalny, zapisany lokalnie)</div>
          <div className="flex items-center gap-2 max-w-md">
            <input
              type="password"
              value={adminToken}
              onChange={(e) => {
                const v = e.target.value
                setAdminToken(v)
                if (typeof window !== 'undefined') {
                  if (v.trim()) localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, v.trim())
                  else localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
                }
              }}
              autoComplete="new-password"
              placeholder="wprowadź token"
              className="flex-1 px-3 py-2 text-xs rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200"
            />
            {adminToken && (
              <span className="text-[10px] text-rldc-green-primary shrink-0">zapisany</span>
            )}
          </div>
          <div className="text-[10px] text-slate-600 mt-1">Token nie jest wyświetlany w trybie plain-text.</div>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={async () => {
              setResetStatus('Resetuję bazę...')
              try {
                const headers: Record<string, string> = withAdminToken()
                const res = await fetch(`${getApiBase()}/api/account/reset?scope=full`, { method: 'POST', headers })
                if (!res.ok) throw new Error('Błąd resetu')
                setResetStatus('Reset zakończony')
              } catch {
                setResetStatus('Reset nieudany')
              }
            }}
            className="px-4 py-2 text-xs rounded bg-rldc-red-primary text-white hover:bg-rldc-red-light transition"
          >
            RESET DB
          </button>
          {resetStatus && <span className="text-xs text-slate-400">{resetStatus}</span>}
        </div>
      </div>

      {!isLogs && (
        <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card mt-4">
          <h2 className="text-lg font-semibold mb-4 text-slate-200">Sterowanie botem</h2>
          {controlStatus && <div className="text-xs text-slate-500 mb-3">{controlStatus}</div>}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">LIVE TRADING — handel włączony</div>
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={() => postControl({ allow_live_trading: !Boolean(controlState?.data?.live_trading_enabled) })}
                  className={`px-3 py-2 text-xs rounded border transition ${
                    controlState?.data?.live_trading_enabled
                      ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
                      : 'bg-rldc-red-primary/15 text-rldc-red-primary border-rldc-red-primary/20'
                  }`}
                >
                  {controlState?.data?.live_trading_enabled ? 'ON' : 'OFF'}
                </button>
                <div className="text-[10px] text-slate-500">
                  aktualizacja: {controlState?.data?.updated_at ? String(controlState.data.updated_at).replace('T', ' ').slice(0, 19) : '--'}
                </div>
              </div>
            </div>

            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">WebSocket (dane żywo)</div>
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={() => postControl({ ws_enabled: !Boolean(controlState?.data?.ws_enabled) })}
                  className={`px-3 py-2 text-xs rounded border transition ${
                    controlState?.data?.ws_enabled
                      ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
                      : 'bg-rldc-red-primary/15 text-rldc-red-primary border-rldc-red-primary/20'
                  }`}
                >
                  {controlState?.data?.ws_enabled ? 'ON' : 'OFF'}
                </button>
              </div>
            </div>

            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Tryb maksymalnej pewności</div>
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={() => postControl({ max_certainty_mode: !Boolean(controlState?.data?.max_certainty_mode) })}
                  className={`px-3 py-2 text-xs rounded border transition ${
                    controlState?.data?.max_certainty_mode
                      ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
                      : 'bg-slate-500/10 text-slate-300 border-rldc-dark-border'
                  }`}
                >
                  {controlState?.data?.max_certainty_mode ? 'ON' : 'OFF'}
                </button>
              </div>
            </div>

            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Waluta kwotowania</div>
              <div className="mt-2 text-sm font-mono text-slate-200">{String(controlState?.data?.demo_quote_ccy || '--')}</div>
            </div>
          </div>

          <div className="mt-4 terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Obserwowane pary (aktywne)</div>
            <div className="mt-2 text-xs text-slate-300 font-mono">
              {Array.isArray(controlState?.data?.watchlist) ? controlState.data.watchlist.join(',') : '--'}
            </div>
            {controlState?.data?.watchlist_source && (
              <div className="mt-1 text-[10px] text-slate-500">
                source: {String(controlState.data.watchlist_source)}              </div>
            )}
          </div>

          <div className="mt-4 terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Nadpisz listę par</div>
            <div className="mt-2 text-xs text-slate-500 mb-2">Wpisz pary oddzielone przecinkami (np. WLFI/EUR,BTC/EUR)</div>
            <input
              value={watchlistOverrideInput}
              onChange={(e) => setWatchlistOverrideInput(e.target.value)}
              placeholder="WLFI/EUR,BTC/EUR"
              className="w-full px-3 py-2 text-xs rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200 font-mono"
            />
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={() => {
                  const list = normalizeWatchlist(watchlistOverrideInput)
                  if (!list.length) {
                    setControlStatus('Podaj przynajmniej 1 symbol albo użyj „Wyłącz nadpisanie”.')
                    return
                  }
                  postControl({ watchlist: list })
                }}
                className="px-4 py-2 text-xs rounded bg-rldc-teal-primary/20 text-rldc-teal-primary hover:bg-rldc-teal-primary/30 transition"
              >
                Zapisz
              </button>
              <button
                onClick={() => postControl({ watchlist: [] })}
                className="px-4 py-2 text-xs rounded bg-slate-500/10 text-slate-200 hover:bg-slate-500/20 transition border border-rldc-dark-border"
              >
                Wyłącz nadpisanie
              </button>
            </div>
          </div>

          {/* Sekcja: Symbol Tiers — tryb HOLD / odblokowanie */}
          {(() => {
            const tiers: Record<string, any> = (controlState?.data?.symbol_tiers as any) || {}
            const holdTierName = Object.keys(tiers).find(k => tiers[k]?.hold_mode)
            const holdTier = holdTierName ? tiers[holdTierName] : null
            const holdSymbols: string[] = holdTier?.symbols || []
            const coreSymbols: string[] = tiers['CORE']?.symbols || []

            const unlockSymbol = async (sym: string) => {
              setHoldStatus('Odblokowuję...')
              try {
                const newTiers = JSON.parse(JSON.stringify(tiers))
                if (holdTierName && newTiers[holdTierName]) {
                  newTiers[holdTierName].symbols = (newTiers[holdTierName].symbols || []).filter((s: string) => s !== sym)
                }
                if (newTiers['CORE']) {
                  if (!newTiers['CORE'].symbols.includes(sym)) {
                    newTiers['CORE'].symbols = [...(newTiers['CORE'].symbols || []), sym]
                  }
                }
                const headers: Record<string, string> = withAdminToken({ 'Content-Type': 'application/json' })
                const res = await fetch(`${getApiBase()}/api/control/state`, { method: 'POST', headers, body: JSON.stringify({ symbol_tiers: newTiers }) })
                if (!res.ok) throw new Error(res.status === 401 ? '401 Unauthorized' : 'Błąd zapisu')
                setHoldStatus(`${sym} odblokowany → CORE`)
                setControlRefreshKey(k => k + 1)
              } catch (e: any) { setHoldStatus(String(e?.message || 'Błąd')) }
            }

            const lockSymbol = async (sym: string) => {
              setHoldStatus('Przełączam w HOLD...')
              try {
                const newTiers = JSON.parse(JSON.stringify(tiers))
                if (newTiers['CORE']) {
                  newTiers['CORE'].symbols = (newTiers['CORE'].symbols || []).filter((s: string) => s !== sym)
                }
                if (!newTiers['HOLD']) {
                  newTiers['HOLD'] = { symbols: [], hold_mode: true, no_auto_exit: true, no_new_entries: true, target_value_eur: 300, risk_scale: 0, max_trades_per_day_per_symbol: 0 }
                }
                if (!newTiers['HOLD'].symbols.includes(sym)) {
                  newTiers['HOLD'].symbols = [...(newTiers['HOLD'].symbols || []), sym]
                }
                newTiers['HOLD'].hold_mode = true
                const headers: Record<string, string> = withAdminToken({ 'Content-Type': 'application/json' })
                const res = await fetch(`${getApiBase()}/api/control/state`, { method: 'POST', headers, body: JSON.stringify({ symbol_tiers: newTiers }) })
                if (!res.ok) throw new Error(res.status === 401 ? '401 Unauthorized' : 'Błąd zapisu')
                setHoldStatus(`${sym} → HOLD`)
                setControlRefreshKey(k => k + 1)
              } catch (e: any) { setHoldStatus(String(e?.message || 'Błąd')) }
            }

            return (
              <div className="mt-4 terminal-card border border-amber-700/30 rounded-lg px-4 py-3 bg-amber-900/10">
                <div className="text-[10px] uppercase tracking-widest text-amber-400 mb-1">Symbol Tiers — tryb HOLD / odblokowanie</div>
                {holdStatus && <div className="text-xs text-slate-400 mb-2">{holdStatus}</div>}
                {holdSymbols.length === 0 && coreSymbols.length === 0 && (
                  <div className="text-xs text-slate-500 mt-1">Brak skonfigurowanych tierów — załaduj kontroler.</div>
                )}
                {holdSymbols.map((sym: string) => (
                  <div key={sym} className="flex items-center gap-3 mt-2 py-1 border-b border-amber-700/20">
                    <span className="font-mono text-amber-300 text-xs w-28">{sym}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-400 border border-amber-700/40">HOLD</span>
                    <span className="text-[10px] text-slate-500">cel: {holdTier?.target_value_eur ?? '--'} EUR</span>
                    <button
                      onClick={() => unlockSymbol(sym)}
                      className="ml-auto px-3 py-1 text-xs rounded bg-rldc-teal-primary/20 text-rldc-teal-primary border border-rldc-teal-primary/30 hover:bg-rldc-teal-primary/30 transition"
                    >
                      Odblokuj → CORE
                    </button>
                  </div>
                ))}
                {coreSymbols.length > 0 && (
                  <div className="mt-3">
                    <div className="text-[10px] text-slate-500 mb-1">Symbole CORE — kliknij „→ HOLD" aby zamrozić:</div>
                    <div className="flex flex-wrap gap-2 mt-1">
                      {coreSymbols.map((sym: string) => (
                        <div key={sym} className="flex items-center gap-1">
                          <span className="font-mono text-xs text-slate-300">{sym}</span>
                          <button
                            onClick={() => lockSymbol(sym)}
                            className="px-2 py-0.5 text-[10px] rounded bg-amber-900/20 text-amber-400 border border-amber-700/30 hover:bg-amber-900/40 transition"
                          >
                            → HOLD
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )
          })()}
        </div>
      )}

      {isLogs && (
        <div className="mt-4">
          {logsLoading && <div className="text-sm text-slate-400 mb-4">Ładowanie logów...</div>}
          {logsError && <div className="text-sm text-rldc-red-primary mb-4">{logsError}</div>}
          <SimpleTable
            title="Logi systemowe (ostatnie)"
            headers={['Czas', 'Poziom', 'Moduł', 'Wiadomość']}
            rows={(logsData?.data || []).map((l: any) => [
              l.timestamp || '--',
              l.level || '--',
              l.module || '--',
              (l.message || '').slice(0, 180),
            ])}
          />
        </div>
      )}
    </div>
  )
}
