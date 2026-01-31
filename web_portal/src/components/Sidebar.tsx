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
  { id: 'galeries', label: 'Galeries', icon: TrendingUp },
  { id: 'trade-desk', label: 'Trade Desk', icon: Target },
  { id: 'portfolio', label: 'Portfolio', icon: Wallet },
  { id: 'strategies', label: 'Strategie', icon: Layers },
  { id: 'ai-signals', label: 'AI & Sygnały', icon: Activity },
  { id: 'decisions', label: 'Decyzje / Ryzyko', icon: BarChart3 },
  { id: 'backtest', label: 'Backtest / Demo', icon: TestTube },
  { id: 'economics', label: 'Economices', icon: BarChart2 },
  { id: 'alertes', label: 'Alertes', icon: Bell },
  { id: 'newsbiance', label: 'Newsbiance', icon: Newspaper },
  { id: 'blog', label: 'Blog', icon: FileText },
  { id: 'usertrimes', label: 'Usertrimes', icon: Settings },
  { id: 'repositories', label: 'Repositories', icon: Terminal },
]

export default function Sidebar({ activeView, setActiveView }: SidebarProps) {
  return (
    <div className="w-64 bg-rldc-dark-card border-r border-rldc-dark-border min-h-[calc(100vh-4rem)] p-4">
      <nav className="space-y-1">
        {menuItems.map((item) => {
          const Icon = item.icon
          const isActive = activeView === item.id
          
          return (
            <button
              key={item.id}
              onClick={() => setActiveView(item.id)}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
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
