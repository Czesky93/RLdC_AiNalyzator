'use client'

import React from 'react'
import MarketOverview from './widgets/MarketOverview'
import TradingView from './widgets/TradingView'
import OpenOrders from './widgets/OpenOrders'
import MarketInsights from './widgets/MarketInsights'

interface MainContentProps {
  activeView: string
  tradingMode: 'live' | 'demo' | 'backtest'
}

export default function MainContent({ activeView, tradingMode }: MainContentProps) {
  if (activeView !== 'dashboard') {
    return (
      <div className="flex-1 p-6">
        <div className="bg-rldc-dark-card rounded-lg p-8 text-center border border-rldc-dark-border">
          <h2 className="text-2xl font-bold text-rldc-teal-primary mb-2">
            {activeView.charAt(0).toUpperCase() + activeView.slice(1)}
          </h2>
          <p className="text-slate-400">
            Ta sekcja będzie dostępna wkrótce
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 p-6 overflow-auto">
      {/* Mode Indicator */}
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold">RLDC AiNalyzer</h1>
        <div className="px-3 py-1 bg-rldc-teal-primary/20 text-rldc-teal-primary rounded text-sm font-medium">
          Tryb: {tradingMode.toUpperCase()}
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-12 gap-4">
        {/* Top Section - Market Overview */}
        <div className="col-span-12">
          <MarketOverview />
        </div>

        {/* Middle Section - Trading View */}
        <div className="col-span-12 lg:col-span-8">
          <TradingView />
        </div>

        {/* Right Section - Market Insights */}
        <div className="col-span-12 lg:col-span-4">
          <MarketInsights />
        </div>

        {/* Bottom Section - Open Orders */}
        <div className="col-span-12">
          <OpenOrders />
        </div>
      </div>
    </div>
  )
}
