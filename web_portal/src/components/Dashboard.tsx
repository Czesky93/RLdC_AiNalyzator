'use client'

import React, { useState } from 'react'
import Topbar from './Topbar'
import Sidebar from './Sidebar'
import MainContent from './MainContent'

export default function Dashboard() {
  const [activeView, setActiveView] = useState('dashboard')
  const [tradingMode, setTradingMode] = useState<'live' | 'demo' | 'backtest'>('demo')

  return (
    <div className="min-h-screen bg-rldc-dark-bg text-slate-100">
      <Topbar 
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
