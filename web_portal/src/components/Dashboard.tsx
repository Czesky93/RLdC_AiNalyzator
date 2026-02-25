'use client'

import React, { useState } from 'react'
import Topbar from './Topbar'
import Sidebar from './Sidebar'
import MainContent from './MainContent'

export default function Dashboard() {
  const [activeView, setActiveView] = useState('dashboard')
  const [tradingMode, setTradingMode] = useState<'live' | 'demo' | 'backtest'>('demo')

  return (
    <div className="min-h-screen text-slate-100 app-shell">
      <Topbar 
        activeView={activeView}
        setActiveView={setActiveView}
        tradingMode={tradingMode} 
        setTradingMode={setTradingMode}
      />
      <div className="flex">
        <Sidebar 
          activeView={activeView} 
          setActiveView={setActiveView} 
        />
        <MainContent 
          activeView={activeView} 
          tradingMode={tradingMode}
        />
      </div>
    </div>
  )
}
