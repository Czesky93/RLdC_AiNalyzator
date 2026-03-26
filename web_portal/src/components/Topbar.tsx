'use client'

import { Bell, ChevronDown, Cloud, Download, Power, Search, User2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { API_BASE, withAdminToken } from '../lib/api'

interface TopbarProps {
  activeView: string
  setActiveView: (view: string) => void
  tradingMode: 'live' | 'demo' | 'backtest'
  setTradingMode: (mode: 'live' | 'demo' | 'backtest') => void
}

export default function Topbar({ activeView, setActiveView, tradingMode, setTradingMode }: TopbarProps) {
  const [tradingEnabled, setTradingEnabled] = useState<boolean | null>(null)
  const [controlError, setControlError] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)

  const navItems = useMemo(
    () => [
      { label: 'Markets', view: 'markets' },
      { label: 'Trade Desk', view: 'trade-desk' },
      { label: 'Portfolio', view: 'portfolio' },
      { label: 'Strategies', view: 'strategies' },
      { label: 'AI & Signals', view: 'ai-signals' },
      { label: 'Risk', view: 'risk' },
      { label: 'Collegues', view: 'collegues' },
    ],
    []
  )

  const refreshControl = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/control/state`)
      if (!res.ok) throw new Error('Błąd control')
      const json = await res.json()
      setTradingEnabled(Boolean(json?.data?.demo_trading_enabled))
      setControlError(null)
    } catch {
      setTradingEnabled(null)
      setControlError('Control offline')
    }
  }

  useEffect(() => {
    refreshControl()
    const t = setInterval(refreshControl, 15000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="sticky top-0 z-50 h-14 bg-gradient-to-r from-[#0b121a]/95 via-[#0f1a24]/95 to-[#0b121a]/95 border-b border-rldc-dark-border flex items-center justify-between px-5 shadow-elevation backdrop-blur-md">
      {/* Left: Logo and Main Menu */}
      <div className="flex items-center space-x-6">
        {/* Logo */}
        <div className="flex items-center space-x-4">
          <div className="text-2xl font-bold text-slate-100 tracking-wider">
            <span className="text-teal-primary">RLDC</span>
          </div>
          
          {/* Basic Dom Dropdown */}
          <div className="relative group">
            <button className="flex items-center space-x-1 px-3 py-1.5 rounded-lg bg-rldc-dark-card border border-rldc-dark-border hover:border-teal-primary/40 transition text-sm text-slate-300">
              <span className="text-xs font-medium">Basic Dom</span>
              <ChevronDown size={14} />
            </button>
          </div>
        </div>

        {/* Navigation */}
        <nav className="hidden lg:flex items-center space-x-1">
          {navItems.map((item) => {
            const isActive = activeView === item.view
            return (
              <button
                key={item.view}
                onClick={() => setActiveView(item.view)}
                className={`px-3 py-1.5 text-xs font-medium transition rounded-md ${
                  isActive 
                    ? 'text-teal-primary bg-teal-primary/10' 
                    : 'text-slate-400 hover:text-slate-200 hover:bg-rldc-dark-hover'
                }`}
              >
                {item.label}
              </button>
            )
          })}
        </nav>
      </div>

      {/* Center: Live Status & Selectors */}
      <div className="hidden xl:flex items-center space-x-3">
        <div className="text-[10px] text-teal-primary font-bold uppercase tracking-wider flex items-center space-x-1.5">
          <div className="w-2 h-2 bg-teal-primary rounded-full animate-pulse"></div>
          <span>LIVE FUTURES RBC-CMC [Streaming] [Exchange] [Exchanges]</span>
        </div>
      </div>

      {/* Right: Controls and Actions */}
      <div className="flex items-center space-x-3">
        {/* Selectors */}
        <div className="hidden lg:flex items-center space-x-2 text-xs">
          <select className="bg-rldc-dark-card border border-rldc-dark-border rounded px-2 py-1 text-slate-300 text-xs focus:outline-none focus:border-teal-primary/50">
            <option>Ser. c6h</option>
          </select>
          <select className="bg-rldc-dark-card border border-rldc-dark-border rounded px-2 py-1 text-slate-300 text-xs focus:outline-none focus:border-teal-primary/50">
            <option>Sym. BTCUSDT</option>
          </select>
          <select className="bg-rldc-dark-card border border-rldc-dark-border rounded px-2 py-1 text-slate-300 text-xs focus:outline-none focus:border-teal-primary/50">
            <option>MAATHG cu PNBET</option>
          </select>
        </div>

        {/* Icon Buttons */}
        <div className="flex items-center gap-1">
          <button className="icon-button" aria-label="Search" title="Wyszukaj">
            <Search size={18} />
          </button>
          <button className="icon-button" aria-label="Alerts" title="Alerty">
            <Bell size={18} />
          </button>
          <button className="icon-button" aria-label="Cloud" title="Chmura">
            <Cloud size={18} />
          </button>
          <button className="icon-button" aria-label="Download" title="Pobierz">
            <Download size={18} />
          </button>
          <button className="icon-button" aria-label="Account" title="Konto">
            <User2 size={18} />
          </button>
        </div>

        {/* Stop Trading Button */}
        <button
          onClick={async () => {
            if (stopping) return
            setStopping(true)
            try {
              const headers: Record<string, string> = withAdminToken({ 'Content-Type': 'application/json' })
              const res = await fetch(`${API_BASE}/api/control/state`, {
                method: 'POST',
                headers,
                body: JSON.stringify({ demo_trading_enabled: false }),
              })
              if (!res.ok) throw new Error('Błąd stop')
              await refreshControl()
            } catch {
              setControlError('STOP TRADING nieudany')
            } finally {
              setStopping(false)
            }
          }}
          className="btn-danger flex items-center space-x-2"
          disabled={stopping || tradingEnabled === false}
          title={tradingEnabled === false ? 'Trading już wyłączony' : 'Wyłącz trading'}
        >
          <Power size={16} />
          <span className="hidden sm:inline">{stopping ? 'STOPPING...' : 'STOP TRADING'}</span>
        </button>
      </div>
    </div>
  )
}
