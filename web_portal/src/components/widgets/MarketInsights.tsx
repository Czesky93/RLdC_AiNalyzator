'use client'

import React from 'react'
import { TrendingUp, AlertCircle, CheckCircle } from 'lucide-react'

const insights = [
  {
    id: '1',
    type: 'signal',
    title: 'Sygnał kupna BTC',
    description: 'RSI wskazuje na oversold, MACD przecięcie wzrostowe',
    confidence: 85,
    time: '2 min temu',
    status: 'active',
  },
  {
    id: '2',
    type: 'alert',
    title: 'Wysoka zmienność ETH',
    description: 'Zwiększona aktywność wielorybów, potencjalny ruch >5%',
    confidence: 72,
    time: '15 min temu',
    status: 'warning',
  },
  {
    id: '3',
    type: 'insight',
    title: 'Pozytywny sentyment rynku',
    description: 'Analiza mediów społecznościowych wskazuje na wzrost optymizmu',
    confidence: 68,
    time: '1 godz. temu',
    status: 'info',
  },
]

export default function MarketInsights() {
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-200">AI Insights</h2>
        <button className="text-xs text-rldc-teal-primary hover:text-rldc-teal-light transition">
          Zobacz wszystkie
        </button>
      </div>

      <div className="space-y-3">
        {insights.map((insight) => (
          <div
            key={insight.id}
            className="bg-rldc-dark-bg rounded-lg p-4 border border-rldc-dark-border hover:border-rldc-teal-primary/50 transition"
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center space-x-2">
                {insight.status === 'active' && (
                  <TrendingUp size={16} className="text-rldc-green-primary" />
                )}
                {insight.status === 'warning' && (
                  <AlertCircle size={16} className="text-yellow-500" />
                )}
                {insight.status === 'info' && (
                  <CheckCircle size={16} className="text-rldc-teal-primary" />
                )}
                <h3 className="text-sm font-semibold text-slate-200">{insight.title}</h3>
              </div>
              <span className="text-xs text-slate-500">{insight.time}</span>
            </div>

            <p className="text-xs text-slate-400 mb-3">{insight.description}</p>

            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <div className="text-xs text-slate-500">Pewność:</div>
                <div className="flex-1 bg-rldc-dark-border rounded-full h-1.5 w-20">
                  <div
                    className="bg-rldc-teal-primary h-1.5 rounded-full"
                    style={{ width: `${insight.confidence}%` }}
                  />
                </div>
                <span className="text-xs font-medium text-rldc-teal-primary">
                  {insight.confidence}%
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Quick Stats */}
      <div className="mt-6 pt-4 border-t border-rldc-dark-border">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Szybkie statystyki</h3>
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Aktywne sygnały</span>
            <span className="font-medium text-rldc-green-primary">12</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Średnia pewność</span>
            <span className="font-medium text-slate-200">78%</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Trafność 24h</span>
            <span className="font-medium text-rldc-green-primary">85%</span>
          </div>
        </div>
      </div>
    </div>
  )
}
