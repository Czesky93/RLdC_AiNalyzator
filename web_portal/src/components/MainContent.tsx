'use client'

import React, { useEffect, useState } from 'react'
import TradingView from './widgets/TradingView'
import OpenOrders from './widgets/OpenOrders'
import MarketInsights from './widgets/MarketInsights'
import DecisionRisk from './widgets/DecisionRisk'
import { ADMIN_TOKEN_STORAGE_KEY, API_BASE, getAdminToken, withAdminToken } from '../lib/api'
import EquityCurve from './widgets/EquityCurve'
import DecisionsRiskPanel from './widgets/DecisionsRiskPanel'

interface MainContentProps {
  activeView: string
  tradingMode: 'live' | 'demo' | 'backtest'
}

function useFetch<T>(url: string, refreshMs: number = 0) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!url) {
      setData(null)
      setLoading(false)
      setError(null)
      return () => {
        cancelled = true
      }
    }
    const fetchData = async () => {
      try {
        const res = await fetch(url)
        if (!res.ok) {
          throw new Error('Błąd pobierania danych')
        }
        const json = await res.json()
        if (!cancelled) {
          setData(json)
        }
      } catch (err) {
        if (!cancelled) {
          setError('Nie udało się pobrać danych')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }
    fetchData()
    const interval = refreshMs > 0 ? setInterval(fetchData, refreshMs) : null
    return () => {
      cancelled = true
      if (interval) clearInterval(interval)
    }
  }, [url, refreshMs])

  return { data, loading, error }
}

function SimpleTable({ title, headers, rows }: { title: string, headers: string[], rows: React.ReactNode[][] }) {
  return (
    <div className="terminal-card rounded-lg p-4 border border-rldc-dark-border neon-card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
        <div className="text-[10px] uppercase tracking-widest terminal-muted">live</div>
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

function ViewHeader({ title }: { title: string }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h1 className="text-2xl font-bold">{title}</h1>
      <div className="px-3 py-1 bg-rldc-teal-primary/20 text-rldc-teal-primary rounded text-sm font-medium">
        Dane z API
      </div>
    </div>
  )
}

export default function MainContent({ activeView, tradingMode }: MainContentProps) {
  if (activeView === 'dashboard') {
    return <DashboardV2View tradingMode={tradingMode} />
  }
  if (activeView === 'dashboard-classic') {
    return <ClassicDashboardView tradingMode={tradingMode} />
  }
  return <OtherView activeView={activeView} tradingMode={tradingMode} />
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
  tradingMode: 'live' | 'demo' | 'backtest'
}) {
  const { data: openaiStatus } = useFetch<any>(`${API_BASE}/api/account/openai-status`, 60000)
  return (
    <div className="mb-4 flex items-center justify-between">
      <h1 className="text-2xl font-bold terminal-title">{title}</h1>
      <div className="flex items-center gap-2">
        <div className="px-3 py-1 bg-rldc-teal-primary/20 text-rldc-teal-primary rounded text-sm font-medium">
          Tryb: {tradingMode.toUpperCase()}
        </div>
        <OpenAIStatusPill status={openaiStatus?.data} />
      </div>
    </div>
  )
}

function DashboardV2View({ tradingMode }: { tradingMode: 'live' | 'demo' | 'backtest' }) {
  const mode = tradingMode === 'live' ? 'live' : 'demo'
  const { data: summary } = useFetch<any>(`${API_BASE}/api/account/summary?mode=${mode}`, 15000)
  const { data: control } = useFetch<any>(`${API_BASE}/api/control/state`, 15000)
  const { data: positions } = useFetch<any>(`${API_BASE}/api/positions?mode=${mode}`, 60000)
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCEUR')

  useEffect(() => {
    const wl = control?.data?.watchlist
    if (!Array.isArray(wl) || !wl.length) return
    if (!selectedSymbol) {
      setSelectedSymbol(String(wl[0]))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [control?.data?.watchlist])

  const quoteCcy = summary?.data?.quote_ccy ? String(summary.data.quote_ccy) : null
  const equity = toNum(summary?.data?.equity)
  const cash = toNum(summary?.data?.cash ?? summary?.data?.balance ?? summary?.data?.free_margin)
  const positionsValue = toNum(summary?.data?.positions_value)
  const unrealized = toNum(summary?.data?.unrealized_pnl)
  const realized24h = toNum(summary?.data?.realized_pnl_24h)
  const roiPct = toNum(summary?.data?.roi) !== null ? (toNum(summary?.data?.roi) as number) * 100 : null

  const tradingEnabled = control?.data?.demo_trading_enabled
  const tradingPill =
    mode === 'demo' ? (
      <div
        className={`px-3 py-1 rounded text-[11px] font-semibold border ${
          tradingEnabled === true
            ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
            : tradingEnabled === false
              ? 'bg-rldc-red-primary/15 text-rldc-red-primary border-rldc-red-primary/20'
              : 'bg-slate-500/10 text-slate-300 border-rldc-dark-border'
        }`}
        title="Control Plane"
      >
        TRADING: {tradingEnabled === null || tradingEnabled === undefined ? '--' : tradingEnabled ? 'ON' : 'OFF'}
      </div>
    ) : null

  const posRows = (positions?.data || []).map((p: any) => [
    p.symbol,
    p.side,
    p.quantity,
    typeof p.entry_price === 'number' ? p.entry_price.toFixed(4) : p.entry_price ?? '--',
    typeof p.current_price === 'number' ? p.current_price.toFixed(4) : p.current_price ?? '--',
    typeof p.unrealized_pnl === 'number' ? p.unrealized_pnl.toFixed(2) : p.unrealized_pnl ?? '--',
  ])

  const kpis = [
    { label: 'Equity', value: formatMoney(quoteCcy, equity), accent: 'text-rldc-green-primary' },
    { label: 'Cash', value: formatMoney(quoteCcy, cash), accent: 'text-slate-100' },
    { label: 'Positions Value', value: formatMoney(quoteCcy, positionsValue), accent: 'text-slate-100' },
    { label: 'Unrealized PnL', value: formatMoney(quoteCcy, unrealized), accent: unrealized && unrealized < 0 ? 'text-rldc-red-primary' : 'text-rldc-green-primary' },
    { label: 'Realized 24h', value: formatMoney(quoteCcy, realized24h), accent: realized24h && realized24h < 0 ? 'text-rldc-red-primary' : 'text-rldc-green-primary' },
    { label: 'ROI', value: formatPct(roiPct), accent: roiPct && roiPct < 0 ? 'text-rldc-red-primary' : 'text-rldc-green-primary' },
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

	        <div className="grid grid-cols-12 gap-4">
	          <div className="col-span-12 lg:col-span-8 space-y-4">
	            <TradingView
	              symbol={selectedSymbol}
	              onSymbolChange={(s) => setSelectedSymbol(s)}
	              allowSymbolSelect={true}
	              refreshMs={60000}
	              titleOverride="Market"
	            />
	            <EquityCurve mode={mode} hours={24} quoteCcy={quoteCcy || undefined} refreshMs={60000} />
	            <div className="grid grid-cols-12 gap-4">
	              <div className="col-span-12 xl:col-span-7">
	                <OpenOrders />
	              </div>
              <div className="col-span-12 xl:col-span-5">
                <SimpleTable
                  title="Positions"
                  headers={['Symbol', 'Side', 'Qty', 'Entry', 'Current', 'uPnL']}
                  rows={posRows}
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

function ClassicDashboardView({ tradingMode }: { tradingMode: 'live' | 'demo' | 'backtest' }) {
  const { data: openaiStatus } = useFetch<any>(`${API_BASE}/api/account/openai-status`, 60000)
  return (
    <div className="flex-1 overflow-auto">
      <div className="p-6 max-w-[1680px] mx-auto">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-bold terminal-title">RLDC Ain Alyzer (Classic)</h1>
          <div className="flex items-center gap-2">
            <div className="px-3 py-1 bg-rldc-teal-primary/20 text-rldc-teal-primary rounded text-sm font-medium">
              Tryb: {tradingMode.toUpperCase()}
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
            <DecisionRisk />
            <PendingOrdersWidget mode={tradingMode === 'live' ? 'live' : 'demo'} />
            <MarketInsights />
          </div>

          <div className="col-span-12 lg:col-span-7">
            <OpenOrders />
          </div>
          <div className="col-span-12 lg:col-span-5">
            <DecisionReasonsWidget />
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
  const { data } = useFetch<any>(`${API_BASE}/api/market/ranges`, 60000)
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
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/market/ranges`, 60000)
  const { data: openaiStatus } = useFetch<any>(`${API_BASE}/api/account/openai-status`, 60000)
  const { data: lastAnalysisErr } = useFetch<any>(
    `${API_BASE}/api/account/system-logs?limit=1&module=analysis&level=ERROR`,
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
      <h2 className="text-lg font-semibold mb-4 text-slate-200">AI Przewidywania</h2>
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
        title="Decyzje kup/sprzedaj"
        headers={['Symbol', 'Decyzja Kupna', 'Cel Kupna', 'Decyzja Sprzedaży', 'Cel Sprzedaży', 'Komentarz', 'Czas']}
        rows={rows}
      />
    </div>
  )
}

function DecisionReasonsWidget() {
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/orders?mode=demo&limit=20`, 60000)
  const rows = (data?.data || []).map((o: any) => [
    o.symbol,
    o.side,
    o.timestamp,
    o.reason || '--',
  ])
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card mt-4">
      <h2 className="text-lg font-semibold mb-4 text-slate-200">Powody decyzji (ostatnie)</h2>
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <SimpleTable
        title="Uzasadnienia"
        headers={['Symbol', 'Side', 'Czas', 'Powód']}
        rows={rows}
      />
    </div>
  )
}

function PendingOrdersWidget({ mode }: { mode: 'demo' | 'live' }) {
  const [refreshKey, setRefreshKey] = useState(0)
  const [actionStatus, setActionStatus] = useState<string | null>(null)
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/orders/pending?mode=${mode}&limit=50&rk=${refreshKey}`, 60000)
  const items = data?.data || []

  const act = async (id: number, action: 'confirm' | 'reject') => {
    setActionStatus(`${action === 'confirm' ? 'Potwierdzam' : 'Odrzucam'} #${id}...`)
    try {
      const headers: Record<string, string> = withAdminToken()
      const res = await fetch(`${API_BASE}/api/orders/pending/${id}/${action}`, { method: 'POST', headers })
      if (!res.ok) throw new Error('Błąd akcji')
      setRefreshKey((k) => k + 1)
      setActionStatus('OK')
    } catch {
      setActionStatus('Akcja nieudana (sprawdź ADMIN_TOKEN)')
    }
  }

  const rows = items.map((p: any) => {
    const canAct = mode === 'demo' && String(p.status || '').toUpperCase() === 'PENDING'
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
      <h2 className="text-lg font-semibold mb-4 text-slate-200">Potwierdzenia (Telegram)</h2>
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      {actionStatus && <div className="text-xs text-slate-500 mb-3">{actionStatus}</div>}
      <SimpleTable
        title="Pending Orders"
        headers={['ID', 'Symbol', 'Side', 'Qty', 'Price', 'Status', 'Czas', 'Akcje']}
        rows={rows}
      />
    </div>
  )
}

function KpiStrip({ tradingMode }: { tradingMode: 'live' | 'demo' | 'backtest' }) {
  const mode = tradingMode === 'live' ? 'live' : 'demo'
  const { data } = useFetch<any>(`${API_BASE}/api/account/kpi?mode=${mode}`, 60000)
  const { data: risk } = useFetch<any>(`${API_BASE}/api/account/risk?mode=${mode}`, 60000)
  const kpi = data?.data || {}
  const riskData = risk?.data || {}
  const items = [
    { label: 'Equity', value: kpi.equity ? `$${kpi.equity.toFixed(2)}` : '--' },
    { label: 'Free Margin', value: kpi.free_margin ? `$${kpi.free_margin.toFixed(2)}` : '--' },
    { label: 'Unrealized PnL', value: kpi.unrealized_pnl ? `$${kpi.unrealized_pnl.toFixed(2)}` : '--' },
    { label: 'Margin Level', value: kpi.margin_level ? `${kpi.margin_level.toFixed(2)}%` : '--' },
    { label: 'Daily Loss Limit', value: riskData.daily_loss_limit ? `${riskData.daily_loss_limit}` : '--' },
    { label: 'Worst DD', value: riskData.worst_drawdown_pct ? `${riskData.worst_drawdown_pct}%` : '--' },
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

function OtherView({ activeView, tradingMode }: MainContentProps) {
  const mode = tradingMode === 'live' ? 'live' : 'demo'

  if (activeView === 'markets') {
    return <MarketsView />
  }
  if (activeView === 'trade-desk') {
    return <TradeDeskView mode={mode} />
  }
  if (activeView === 'portfolio') {
    return <PortfolioView mode={mode} />
  }
  if (activeView === 'strategies') {
    return <StrategiesView />
  }
  if (activeView === 'ai-signals') {
    return <SignalsView />
  }
  if (activeView === 'decisions') {
    return <DecisionsView mode={mode} />
  }
  if (activeView === 'backtest') {
    return <BacktestView mode={mode} />
  }
  if (activeView === 'economics' || activeView === 'alerts' || activeView === 'news') {
    return <MarketProxyView activeView={activeView} />
  }
  if (activeView === 'blog') {
    return <BlogView />
  }
  if (activeView === 'settings' || activeView === 'logs') {
    return <SettingsView activeView={activeView} mode={mode} />
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

function MarketsView() {
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/market/summary`)
  const { data: rangesData } = useFetch<any>(`${API_BASE}/api/market/ranges`)
  const { data: quantum } = useFetch<any>(`${API_BASE}/api/market/quantum`)
  const rangesMap = new Map<string, any>((rangesData?.data || []).map((r: any) => [r.symbol, r]))
  const qMap = new Map<string, any>((quantum?.data || []).map((q: any) => [q.symbol, q]))
  const rows = (data?.data || []).map((m: any) => {
    const r: any = rangesMap.get(m.symbol)
    const q: any = qMap.get(m.symbol)
    const buyRange = r ? `${r.buy_low} - ${r.buy_high}` : '--'
    const sellRange = r ? `${r.sell_low} - ${r.sell_high}` : '--'
    return [
      m.symbol,
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
      <ViewHeader title="Rynki" />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <SimpleTable
        title="Przegląd Rynku"
        headers={['Symbol', 'Cena', 'Zmiana', 'Zmiana %', 'Wolumen', 'BUY zakres', 'SELL zakres', 'Waga Q', 'Vol Q']}
        rows={rows}
      />
    </div>
  )
}

function TradeDeskView({ mode }: { mode: 'demo' | 'live' }) {
  const [symbolFilter, setSymbolFilter] = useState<string>('ALL')
  const [rangeHours, setRangeHours] = useState<number>(24)
  const { data: orders, loading: loadingOrders, error: errorOrders } = useFetch<any>(`${API_BASE}/api/orders?mode=${mode}&limit=200`)
  const { data: positions, loading: loadingPos, error: errorPos } = useFetch<any>(`${API_BASE}/api/positions?mode=${mode}`)
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
  const positionRows = (positions?.data || []).map((p: any) => [
    p.symbol,
    p.side,
    p.quantity,
    p.entry_price?.toFixed(2),
    p.current_price?.toFixed(2),
    p.unrealized_pnl?.toFixed(2),
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Panel Transakcyjny" />
      {(loadingOrders || loadingPos) && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {(errorOrders || errorPos) && <div className="text-sm text-rldc-red-primary mb-4">Nie udało się pobrać danych</div>}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 bg-rldc-dark-card rounded-lg p-4 border border-rldc-dark-border neon-card">
          <div className="flex flex-wrap items-center gap-4">
            <div className="text-xs text-slate-500">Filtry:</div>
            <select
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
            headers={['Symbol', 'Side', 'Typ', 'Ilość', 'Status', 'Czas', 'Powód']}
            rows={orderRows}
          />
        </div>
        <div className="col-span-12">
          <SimpleTable
            title="Pozycje"
            headers={['Symbol', 'Side', 'Ilość', 'Wejście', 'Obecna', 'PnL']}
            rows={positionRows}
          />
        </div>
      </div>
    </div>
  )
}

function PortfolioView({ mode }: { mode: 'demo' | 'live' }) {
  const { data: portfolio, loading, error } = useFetch<any>(`${API_BASE}/api/portfolio?mode=${mode}`)
  const rows = (portfolio?.data || []).map((p: any) => [
    p.symbol,
    p.side,
    p.quantity,
    p.entry_price?.toFixed(2),
    p.current_price?.toFixed(2),
    p.unrealized_pnl?.toFixed(2),
  ])
  const spotRows = (portfolio?.spot_balances || []).map((b: any) => [
    b.asset,
    b.free,
    b.locked,
    b.total,
  ])
  const futuresRows = (portfolio?.futures_balance || []).map((b: any) => [
    b.asset,
    b.balance,
    b.availableBalance,
    b.withdrawAvailable,
  ])
  const earnFlexible = (portfolio?.simple_earn_flexible?.rows || portfolio?.simple_earn_flexible?.data || []).map((p: any) => [
    p.asset || p.assetName,
    p.totalAmount || p.amount,
    p.redeemAmount || p.redeemableAmount,
    p.apr || p.latestAnnualPercentageRate,
  ])
  const earnLocked = (portfolio?.simple_earn_locked?.rows || portfolio?.simple_earn_locked?.data || []).map((p: any) => [
    p.asset || p.assetName,
    p.amount || p.totalAmount,
    p.positionId || p.projectId || '--',
    p.apr || p.latestAnnualPercentageRate,
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Portfel" />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      {mode === 'live' && (
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 lg:col-span-6">
            <SimpleTable
              title="Spot Balances"
              headers={['Asset', 'Free', 'Locked', 'Total']}
              rows={spotRows}
            />
          </div>
          <div className="col-span-12 lg:col-span-6">
            <SimpleTable
              title="Futures Balance"
              headers={['Asset', 'Balance', 'Available', 'Withdrawable']}
              rows={futuresRows}
            />
          </div>
          <div className="col-span-12 lg:col-span-6">
            <SimpleTable
              title="Simple Earn Flexible"
              headers={['Asset', 'Amount', 'Redeemable', 'APR']}
              rows={earnFlexible}
            />
          </div>
          <div className="col-span-12 lg:col-span-6">
            <SimpleTable
              title="Simple Earn Locked"
              headers={['Asset', 'Amount', 'Position', 'APR']}
              rows={earnLocked}
            />
          </div>
        </div>
      )}
      {mode !== 'live' && (
        <SimpleTable
          title="Otwarte Pozycje"
          headers={['Symbol', 'Side', 'Ilość', 'Wejście', 'Obecna', 'PnL']}
          rows={rows}
        />
      )}
    </div>
  )
}

function StrategiesView() {
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/signals/top10`)
  const rows = (data?.data || []).map((s: any) => [
    s.symbol,
    s.signal_type,
    `${Math.round(s.confidence * 100)}%`,
    s.price?.toFixed(2),
    s.timestamp,
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Strategie" />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <SimpleTable
        title="Top 10 Sygnałów"
        headers={['Symbol', 'Sygnał', 'Pewność', 'Cena', 'Czas']}
        rows={rows}
      />
    </div>
  )
}

function SignalsView() {
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/signals/latest?limit=20`)
  const rows = (data?.data || []).map((s: any) => [
    s.symbol,
    s.signal_type,
    `${Math.round(s.confidence * 100)}%`,
    s.price?.toFixed(2),
    s.timestamp,
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="AI & Sygnały" />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <SimpleTable
        title="Najnowsze sygnały"
        headers={['Symbol', 'Sygnał', 'Pewność', 'Cena', 'Czas']}
        rows={rows}
      />
    </div>
  )
}

function DecisionsView({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/account/kpi?mode=${mode}`)
  const { data: risk } = useFetch<any>(`${API_BASE}/api/account/risk?mode=${mode}`)
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Decyzje i Ryzyko" />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      {risk?.data?.daily_loss_triggered && (
        <div className="mb-4 bg-rldc-red-primary/20 border border-rldc-red-primary text-rldc-red-primary px-4 py-3 rounded">
          Limit dziennej straty przekroczony — demo trading wstrzymany.
        </div>
      )}
      {risk?.data?.drawdown_triggered && (
        <div className="mb-4 bg-yellow-500/20 border border-yellow-500 text-yellow-400 px-4 py-3 rounded">
          Drawdown przekroczony na pozycji — sprawdź ryzyko.
        </div>
      )}
      <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
        <h2 className="text-lg font-semibold mb-4 text-slate-200">KPI Konta</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-slate-500 mb-1">Equity</div>
            <div className="text-lg font-bold text-slate-100">${data?.data?.equity?.toFixed(2) || '--'}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Unrealized PnL</div>
            <div className="text-lg font-bold text-rldc-green-primary">${data?.data?.unrealized_pnl?.toFixed(2) || '--'}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Free Margin</div>
            <div className="text-lg font-bold text-slate-100">${data?.data?.free_margin?.toFixed(2) || '--'}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Margin Level</div>
            <div className="text-lg font-bold text-slate-100">{data?.data?.margin_level?.toFixed(2) || '--'}%</div>
          </div>
        </div>
      </div>
      <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border mt-4 neon-card">
        <h2 className="text-lg font-semibold mb-4 text-slate-200">Limity ryzyka</h2>
        <div className="grid grid-cols-2 gap-4 text-sm text-slate-300">
          <div>Maks. dzienna strata: {risk?.data?.max_daily_loss_pct ?? '--'}%</div>
          <div>Limit dzienny: {risk?.data?.daily_loss_limit ?? '--'}</div>
          <div>Maks. drawdown: {risk?.data?.max_drawdown_pct ?? '--'}%</div>
          <div>Najgorszy drawdown: {risk?.data?.worst_drawdown_pct ?? '--'}%</div>
        </div>
      </div>
    </div>
  )
}

function BacktestView({ mode }: { mode: 'demo' | 'live' }) {
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/orders/stats?mode=${mode}&days=30`)
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Backtest i Demo" />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
        <h2 className="text-lg font-semibold mb-4 text-slate-200">Statystyki zleceń (30 dni)</h2>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <div className="text-xs text-slate-500 mb-1">Łącznie</div>
            <div className="text-lg font-bold text-slate-100">{data?.data?.total || 0}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">FILLED</div>
            <div className="text-lg font-bold text-rldc-green-primary">{data?.data?.filled || 0}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Fill Rate</div>
            <div className="text-lg font-bold text-slate-100">{data?.data?.fill_rate || 0}%</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function MarketProxyView({ activeView }: { activeView: string }) {
  const title = activeView === 'economics' ? 'Ekonomia' : activeView === 'alerts' ? 'Alerty' : 'News i Sentyment'
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/market/summary`)
  const rows = (data?.data || []).map((m: any) => [
    m.symbol,
    m.price?.toFixed(2),
    m.price_change?.toFixed(2),
    `${m.price_change_percent?.toFixed(2)}%`,
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title={title} />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <SimpleTable
        title="Dane rynkowe (proxy)"
        headers={['Symbol', 'Cena', 'Zmiana', 'Zmiana %']}
        rows={rows}
      />
    </div>
  )
}

function BlogView() {
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/blog/list?limit=10`)
  const rows = (data?.data || []).map((p: any) => [
    p.title,
    p.status,
    p.created_at,
  ])
  return (
    <div className="flex-1 p-6 overflow-auto">
      <ViewHeader title="Blog" />
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

function SettingsView({ activeView, mode }: { activeView: string, mode: 'demo' | 'live' }) {
  const isLogs = activeView === 'logs'
  const title = isLogs ? 'Logi' : 'Ustawienia'
  const { data, loading, error } = useFetch<any>(`${API_BASE}/api/account/summary?mode=${mode}`, isLogs ? 60000 : 0)
  const [controlRefreshKey, setControlRefreshKey] = useState(0)
  const { data: controlState } = useFetch<any>(
    `${API_BASE}/api/control/state?rk=${controlRefreshKey}`,
    isLogs ? 0 : 15000
  )
  const { data: logsData, loading: logsLoading, error: logsError } = useFetch<any>(
    isLogs ? `${API_BASE}/api/account/system-logs?limit=80` : '',
    isLogs ? 60000 : 0
  )
  const [resetStatus, setResetStatus] = useState<string | null>(null)
  const [adminToken, setAdminToken] = useState<string>('')
  const [controlStatus, setControlStatus] = useState<string | null>(null)
  const [watchlistOverrideInput, setWatchlistOverrideInput] = useState<string>('')

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
      const res = await fetch(`${API_BASE}/api/control/state`, {
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
      <ViewHeader title={title} />
      {loading && <div className="text-sm text-slate-400 mb-4">Ładowanie...</div>}
      {error && <div className="text-sm text-rldc-red-primary mb-4">{error}</div>}
      <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border neon-card">
        <h2 className="text-lg font-semibold mb-4 text-slate-200">Podstawowe dane konta</h2>
        <div className="text-sm text-slate-400">
          Equity: {data?.data?.equity?.toFixed(2) || '--'} | Balance: {data?.data?.balance?.toFixed(2) || '--'}
        </div>
        <div className="mt-4">
          <div className="text-xs text-slate-500 mb-2">Admin token (opcjonalny, localStorage)</div>
          <input
            value={adminToken}
            onChange={(e) => {
              const v = e.target.value
              setAdminToken(v)
              if (typeof window !== 'undefined') {
                if (v.trim()) localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, v.trim())
                else localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
              }
            }}
            placeholder="X-Admin-Token"
            className="w-full max-w-md px-3 py-2 text-xs rounded bg-rldc-dark-bg border border-rldc-dark-border text-slate-200"
          />
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={async () => {
              setResetStatus('Resetuję bazę...')
              try {
                const headers: Record<string, string> = withAdminToken()
                const res = await fetch(`${API_BASE}/api/account/reset?scope=full`, { method: 'POST', headers })
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
          <h2 className="text-lg font-semibold mb-4 text-slate-200">Control Plane</h2>
          {controlStatus && <div className="text-xs text-slate-500 mb-3">{controlStatus}</div>}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">DEMO trading</div>
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={() => postControl({ demo_trading_enabled: !Boolean(controlState?.data?.demo_trading_enabled) })}
                  className={`px-3 py-2 text-xs rounded border transition ${
                    controlState?.data?.demo_trading_enabled
                      ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
                      : 'bg-rldc-red-primary/15 text-rldc-red-primary border-rldc-red-primary/20'
                  }`}
                >
                  {controlState?.data?.demo_trading_enabled ? 'ON' : 'OFF'}
                </button>
                <div className="text-xs text-slate-500">
                  updated: {String(controlState?.data?.updated_at || '--')}
                </div>
              </div>
            </div>

            <div className="terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">WS enabled</div>
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
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Max certainty mode</div>
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
              <div className="text-[10px] uppercase tracking-widest text-slate-500">DEMO quote ccy</div>
              <div className="mt-2 text-sm font-mono text-slate-200">{String(controlState?.data?.demo_quote_ccy || '--')}</div>
            </div>
          </div>

          <div className="mt-4 terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Effective watchlist</div>
            <div className="mt-2 text-xs text-slate-300 font-mono">
              {Array.isArray(controlState?.data?.watchlist) ? controlState.data.watchlist.join(',') : '--'}
            </div>
            {controlState?.data?.watchlist_source && (
              <div className="mt-1 text-[10px] text-slate-500">
                source: {String(controlState.data.watchlist_source)}
              </div>
            )}
          </div>

          <div className="mt-4 terminal-card border border-rldc-dark-border rounded-lg px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Watchlist override</div>
            <div className="mt-2 text-xs text-slate-500 mb-2">comma-separated (np. WLFI/EUR,BTC/EUR)</div>
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
                    setControlStatus('Podaj przynajmniej 1 symbol albo użyj Clear override.')
                    return
                  }
                  postControl({ watchlist: list })
                }}
                className="px-4 py-2 text-xs rounded bg-rldc-teal-primary/20 text-rldc-teal-primary hover:bg-rldc-teal-primary/30 transition"
              >
                Save override
              </button>
              <button
                onClick={() => postControl({ watchlist: [] })}
                className="px-4 py-2 text-xs rounded bg-slate-500/10 text-slate-200 hover:bg-slate-500/20 transition border border-rldc-dark-border"
              >
                Clear override
              </button>
            </div>
          </div>
        </div>
      )}

      {isLogs && (
        <div className="mt-4">
          {logsLoading && <div className="text-sm text-slate-400 mb-4">Ładowanie logów...</div>}
          {logsError && <div className="text-sm text-rldc-red-primary mb-4">{logsError}</div>}
          <SimpleTable
            title="System logs (ostatnie)"
            headers={['Czas', 'Level', 'Moduł', 'Wiadomość']}
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
