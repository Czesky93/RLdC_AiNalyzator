'use client'

import React from 'react'
import {
  LayoutDashboard,
  TrendingUp,
  Target,
  Wallet,
  Layers,
  Activity,
  BarChart3,
  TestTube,
  Bell,
  Newspaper,
  BarChart2,
  FileText,
  Settings,
  Terminal,
} from 'lucide-react'

interface SidebarProps {
  activeView: string
  setActiveView: (view: string) => void
}

const menuItems = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'dashboard-classic', label: 'Dashboard (Classic)', icon: LayoutDashboard },
  { id: 'markets', label: 'Markets', icon: TrendingUp },
  { id: 'trade-desk', label: 'Trade Desk', icon: Target },
  { id: 'portfolio', label: 'Portfolio', icon: Wallet },
  { id: 'strategies', label: 'Strategie', icon: Layers },
  { id: 'ai-signals', label: 'AI & Sygnały', icon: Activity },
  { id: 'decisions', label: 'Decyzje / Ryzyko', icon: BarChart3 },
  { id: 'backtest', label: 'Backtest / Demo', icon: TestTube },
  { id: 'economics', label: 'Economics', icon: BarChart2 },
  { id: 'alerts', label: 'Alerty', icon: Bell },
  { id: 'news', label: 'News & Sentyment', icon: Newspaper },
  { id: 'blog', label: 'Blog', icon: FileText },
  { id: 'settings', label: 'Ustawienia', icon: Settings },
  { id: 'logs', label: 'Logi', icon: Terminal },
]

export default function Sidebar({ activeView, setActiveView }: SidebarProps) {
  return (
    <div className="w-64 bg-[#0b121a] border-r border-rldc-dark-border min-h-[calc(100vh-3.5rem)] p-4 shadow-[inset_-1px_0_0_rgba(255,255,255,0.04)]">
      <div className="mb-4 px-2">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest">FUTURES</div>
        <div className="mt-2 flex items-center justify-between">
          <div className="text-xs text-slate-300">BTC/USDT</div>
          <div className="px-2 py-0.5 rounded bg-rldc-dark-bg border border-rldc-dark-border text-[10px] text-slate-400">
            ACTIVE
          </div>
        </div>
      </div>
      <nav className="space-y-1">
        {menuItems.map((item) => {
          const Icon = item.icon
          const isActive = activeView === item.id
          
          return (
            <button
              key={item.id}
              onClick={() => setActiveView(item.id)}
              className={`w-full flex items-center space-x-3 px-4 py-2.5 rounded-lg text-[13px] font-medium transition ${
                isActive
                  ? 'bg-rldc-teal-primary/10 text-rldc-teal-primary border-l-2 border-rldc-teal-primary'
                  : 'text-slate-400 hover:bg-rldc-dark-hover hover:text-slate-200'
              }`}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          )
        })}
      </nav>
    </div>
  )
}
