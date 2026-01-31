'use client'

import React from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'

const marketData = [
  {
    symbol: 'BTC/USDT',
    price: '€20,587',
    change: '+71,981',
    changePercent: '+3.6%',
    trend: 'up',
    volume: '244s',
  },
  {
    symbol: 'ETH/USDT',
    price: '€1,654',
    change: '-12',
    changePercent: '-0.7%',
    trend: 'down',
    volume: '156s',
  },
  {
    symbol: 'SOL/USDT',
    price: '€98.4',
    change: '+5.2',
    changePercent: '+5.6%',
    trend: 'up',
    volume: '89s',
  },
  {
    symbol: 'MATIC/USDT',
    price: '€0.824',
    change: '-0.012',
    changePercent: '-1.4%',
    trend: 'down',
    volume: '67s',
  },
]

export default function MarketOverview() {
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border">
      <h2 className="text-lg font-semibold mb-4 text-slate-200">Przegląd Rynku</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {marketData.map((item) => (
          <div
            key={item.symbol}
            className="bg-rldc-dark-bg rounded-lg p-4 border border-rldc-dark-border hover:border-rldc-teal-primary/50 transition"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-slate-400">{item.symbol}</span>
              {item.trend === 'up' ? (
                <TrendingUp size={16} className="text-rldc-green-primary" />
              ) : (
                <TrendingDown size={16} className="text-rldc-red-primary" />
              )}
            </div>
            
            <div className="text-2xl font-bold text-slate-100 mb-1">
              {item.price}
            </div>
            
            <div className="flex items-center justify-between text-sm">
              <span className={item.trend === 'up' ? 'text-rldc-green-primary' : 'text-rldc-red-primary'}>
                {item.change} ({item.changePercent})
              </span>
              <span className="text-slate-500">{item.volume}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
