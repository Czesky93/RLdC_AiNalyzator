'use client'

import React from 'react'
import { Power, Bell, Search, User2, Twitter } from 'lucide-react'

interface TopbarProps {
  tradingMode: 'live' | 'demo' | 'backtest'
  setTradingMode: (mode: 'live' | 'demo' | 'backtest') => void
}

export default function Topbar({ tradingMode, setTradingMode }: TopbarProps) {
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

        {/* Stop Trading Button */}
        <button className="flex items-center space-x-2 bg-rldc-orange-primary hover:bg-rldc-orange-light text-slate-900 px-4 py-2 rounded-lg text-sm font-semibold transition shadow-[0_0_28px_rgba(245,158,11,0.35)]">
          <Power size={16} />
          <span>STOP TRADING</span>
        </button>
      </div>
    </div>
  )
}
