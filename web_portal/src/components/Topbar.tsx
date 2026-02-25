'use client'

import { useEffect, useState } from 'react'
import { Bell, Power, Search, Twitter, User2 } from 'lucide-react'

interface TopbarProps {
  tradingMode: 'live' | 'demo' | 'backtest'
  setTradingMode: (mode: 'live' | 'demo' | 'backtest') => void
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const ADMIN_TOKEN_STORAGE_KEY = 'rldc_admin_token'

function getAdminToken(): string {
  if (typeof window === 'undefined') return ''
  return localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) || ''
}

export default function Topbar({ tradingMode, setTradingMode }: TopbarProps) {
  const [tradingEnabled, setTradingEnabled] = useState<boolean | null>(null)
  const [controlError, setControlError] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)

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
    <div className="sticky top-0 z-50 h-14 bg-gradient-to-r from-[#0b121a]/90 via-[#0f1a24]/90 to-[#0b121a]/90 border-b border-rldc-dark-border flex items-center justify-between px-5 shadow-[0_12px_35px_rgba(0,0,0,0.55)] backdrop-blur">
      {/* Left: Logo and Navigation */}
      <div className="flex items-center space-x-8">
        <div className="text-3xl font-bold text-slate-100 tracking-wide neon-text">
          RLDC
        </div>
        <nav className="hidden md:flex items-center space-x-5 text-[11px] uppercase tracking-widest">
          {['Dashboard', 'Markets', 'Trade Desk', 'Portfolio', 'Strategies', 'AI & Signals', 'Risk'].map((item) => (
            <a
              key={item}
              href="#"
              className="text-slate-300 hover:text-rldc-teal-light transition relative after:absolute after:inset-x-0 after:-bottom-4 after:h-0.5 after:bg-rldc-teal-light after:scale-x-0 hover:after:scale-x-100 after:transition"
            >
              {item}
            </a>
          ))}
        </nav>
      </div>

      {/* Right: Mode Selector and Actions */}
      <div className="flex items-center space-x-4">
        {/* Trading Mode Selector */}
        <div className="hidden sm:flex bg-rldc-dark-bg rounded-lg overflow-hidden border border-rldc-dark-border glow-border">
          {(['demo', 'live', 'backtest'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setTradingMode(mode)}
              className={`px-4 py-2 text-xs font-medium transition ${
                tradingMode === mode
                  ? 'bg-rldc-teal-primary text-white'
                  : 'text-slate-400 hover:text-rldc-teal-light'
              }`}
            >
              {mode.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="hidden lg:flex items-center gap-1">
          <button className="p-2 hover:bg-rldc-dark-hover rounded-lg transition" aria-label="Search">
            <Search size={18} className="text-slate-300" />
          </button>
          <button className="p-2 hover:bg-rldc-dark-hover rounded-lg transition" aria-label="Twitter">
            <Twitter size={18} className="text-slate-300" />
          </button>
          <button className="p-2 hover:bg-rldc-dark-hover rounded-lg transition" aria-label="Notifications">
            <Bell size={18} className="text-slate-300" />
          </button>
          <button className="p-2 hover:bg-rldc-dark-hover rounded-lg transition" aria-label="Account">
            <User2 size={18} className="text-slate-300" />
          </button>
        </div>

        {/* Trading State */}
        {tradingMode === 'demo' && (
          <div
            className={`hidden md:flex items-center px-3 py-1 rounded text-[11px] font-semibold border ${
              tradingEnabled === true
                ? 'bg-rldc-green-primary/15 text-rldc-green-primary border-rldc-green-primary/20'
                : tradingEnabled === false
                  ? 'bg-rldc-red-primary/15 text-rldc-red-primary border-rldc-red-primary/20'
                  : 'bg-slate-500/10 text-slate-300 border-rldc-dark-border'
            }`}
            title={controlError || 'DEMO trading state'}
          >
            TRADING: {tradingEnabled === null ? '--' : tradingEnabled ? 'ON' : 'OFF'}
          </div>
        )}

        {/* Stop Trading Button */}
        <button
          onClick={async () => {
            if (stopping) return
            setStopping(true)
            try {
              const token = getAdminToken().trim()
              const headers: Record<string, string> = { 'Content-Type': 'application/json' }
              if (token) headers['X-Admin-Token'] = token
              const res = await fetch(`${API_BASE}/api/control/state`, {
                method: 'POST',
                headers,
                body: JSON.stringify({ demo_trading_enabled: false }),
              })
              if (!res.ok) throw new Error('Błąd stop')
              await refreshControl()
            } catch {
              setControlError('STOP TRADING nieudany (ADMIN_TOKEN?)')
            } finally {
              setStopping(false)
            }
          }}
          className="flex items-center space-x-2 bg-rldc-orange-primary hover:bg-rldc-orange-light disabled:opacity-60 disabled:cursor-not-allowed text-slate-900 px-4 py-2 rounded-lg text-sm font-semibold transition shadow-[0_0_28px_rgba(245,158,11,0.35)]"
          disabled={stopping || tradingEnabled === false}
          title={tradingEnabled === false ? 'Trading już wyłączony' : 'Wyłącz DEMO trading'}
        >
          <Power size={16} />
          <span>{stopping ? 'STOPPING...' : 'STOP TRADING'}</span>
        </button>
      </div>
    </div>
  )
}
