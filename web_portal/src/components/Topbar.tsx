'use client'

import React from 'react'
import { Power, AlertTriangle } from 'lucide-react'

interface TopbarProps {
  tradingMode: 'live' | 'demo' | 'backtest'
  setTradingMode: (mode: 'live' | 'demo' | 'backtest') => void
}

export default function Topbar({ tradingMode, setTradingMode }: TopbarProps) {
  return (
    <div className="h-16 bg-rldc-dark-card border-b border-rldc-dark-border flex items-center justify-between px-6">
      {/* Left: Logo and Navigation */}
      <div className="flex items-center space-x-8">
        <div className="text-2xl font-bold text-rldc-teal-primary">
          RLDC
        </div>
        <nav className="flex items-center space-x-6 text-sm">
          <a href="#" className="text-slate-300 hover:text-rldc-teal-primary transition">Dashboard</a>
          <a href="#" className="text-slate-300 hover:text-rldc-teal-primary transition">Markets</a>
          <a href="#" className="text-slate-300 hover:text-rldc-teal-primary transition">Sygnały</a>
          <a href="#" className="text-slate-300 hover:text-rldc-teal-primary transition">Trade Desk</a>
        </nav>
      </div>

      {/* Right: Mode Selector and Actions */}
      <div className="flex items-center space-x-4">
        {/* Trading Mode Selector */}
        <div className="flex bg-rldc-dark-bg rounded-lg overflow-hidden">
          {(['demo', 'live', 'backtest'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setTradingMode(mode)}
              className={`px-4 py-2 text-xs font-medium transition ${
                tradingMode === mode
                  ? 'bg-rldc-teal-primary text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {mode.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Stop Trading Button */}
        <button className="flex items-center space-x-2 bg-rldc-red-primary hover:bg-red-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition">
          <Power size={16} />
          <span>STOP TRADING</span>
        </button>

        {/* Alerts */}
        <button className="p-2 hover:bg-rldc-dark-hover rounded-lg transition">
          <AlertTriangle size={20} className="text-yellow-500" />
        </button>
      </div>
    </div>
  )
}
