# RLDC AiNalyzer - Biblioteka Komponentów

## Przegląd

Dokumentacja wielokrotnego użytku komponentów UI dla platformy RLDC AiNalyzer.

## Komponenty Layoutu

### Dashboard
**Lokalizacja:** `web_portal/src/components/Dashboard.tsx`

Główny kontener aplikacji zarządzający stanem i layoutem.

```tsx
import Dashboard from '@/components/Dashboard'

export default function Home() {
  return <Dashboard />
}
```

**Props:** Brak (zarządza własnym stanem)

**Stan:**
- `activeView: string` - Aktualnie aktywny widok (dashboard, markets, etc.)
- `tradingMode: 'live' | 'demo' | 'backtest'` - Tryb tradingu

---

### Topbar
**Lokalizacja:** `web_portal/src/components/Topbar.tsx`

Górny pasek nawigacji z logo, menu i kontrolkami.

```tsx
<Topbar 
  tradingMode={tradingMode} 
  setTradingMode={setTradingMode}
/>
```

**Props:**
- `tradingMode: 'live' | 'demo' | 'backtest'` - Aktualny tryb
- `setTradingMode: (mode) => void` - Callback do zmiany trybu

**Funkcje:**
- Nawigacja główna (Dashboard, Markets, Sygnały, Trade Desk)
- Przełącznik trybu (DEMO/LIVE/BACKTEST)
- Przycisk STOP TRADING
- Ikona alertów

---

### Sidebar
**Lokalizacja:** `web_portal/src/components/Sidebar.tsx`

Boczne menu nawigacyjne.

```tsx
<Sidebar 
  activeView={activeView} 
  setActiveView={setActiveView} 
/>
```

**Props:**
- `activeView: string` - ID aktywnego widoku
- `setActiveView: (view: string) => void` - Callback zmiany widoku

**Menu Items:**
- dashboard - Dashboard
- galeries - Galeries
- trade-desk - Trade Desk
- portfolio - Portfolio
- strategies - Strategie
- ai-signals - AI & Sygnały
- decisions - Decyzje / Ryzyko
- backtest - Backtest / Demo
- economics - Economices
- alertes - Alertes
- newsbiance - Newsbiance
- blog - Blog
- usertrimes - Usertrimes
- repositories - Repositories

---

### MainContent
**Lokalizacja:** `web_portal/src/components/MainContent.tsx`

Obszar głównej zawartości, renderuje widoki w zależności od `activeView`.

```tsx
<MainContent 
  activeView={activeView} 
  tradingMode={tradingMode}
/>
```

**Props:**
- `activeView: string` - ID widoku do wyświetlenia
- `tradingMode: 'live' | 'demo' | 'backtest'` - Aktualny tryb

---

## Komponenty Widżetów

### MarketOverview
**Lokalizacja:** `web_portal/src/components/widgets/MarketOverview.tsx`

Przegląd kart rynkowych z kluczowymi parami i cenami.

```tsx
import MarketOverview from '@/components/widgets/MarketOverview'

<MarketOverview />
```

**Wyświetla:**
- Karty z parami handlowymi (BTC/USDT, ETH/USDT, etc.)
- Aktualna cena
- Zmiana ceny (wartość i procent)
- Trend (up/down) z ikoną
- Wolumen

**Style:**
- Grid responsywny (1 kolumna mobile, 2 tablet, 4 desktop)
- Hover effect na kartach
- Ikony TrendingUp/TrendingDown
- Kolory: zielony dla wzrostów, czerwony dla spadków

---

### TradingView
**Lokalizacja:** `web_portal/src/components/widgets/TradingView.tsx`

Wykres tradingowy z danymi cenowymi.

```tsx
import TradingView from '@/components/widgets/TradingView'

<TradingView />
```

**Funkcje:**
- Wykres area chart (Recharts)
- Selektor timeframe (1m, 5m, 15m, 1h, 4h, 1D)
- Aktualna cena i zmiana 24h
- Statystyki: 24h Max, Min, Wolumen, Zmienność

**Dane wykresu:**
```typescript
interface ChartData {
  time: string      // Timestamp wyświetlany
  price: number     // Cena
  volume: number    // Wolumen (opcjonalny)
}
```

**Customizacja:**
- Gradient fill pod linią
- Siatka z kolorem `#1e2d3d`
- Tooltip z dark theme
- Responsywny (100% width/height)

---

### MarketInsights
**Lokalizacja:** `web_portal/src/components/widgets/MarketInsights.tsx`

Panel z AI insights i sygnałami.

```tsx
import MarketInsights from '@/components/widgets/MarketInsights'

<MarketInsights />
```

**Wyświetla:**
- Lista insights z ikonami statusu
- Procent pewności (confidence bar)
- Czas publikacji
- Szybkie statystyki

**Typy insights:**
```typescript
interface Insight {
  id: string
  type: 'signal' | 'alert' | 'insight'
  title: string
  description: string
  confidence: number    // 0-100
  time: string
  status: 'active' | 'warning' | 'info'
}
```

**Ikony statusu:**
- `active`: TrendingUp (zielony)
- `warning`: AlertCircle (żółty)
- `info`: CheckCircle (teal)

---

### OpenOrders
**Lokalizacja:** `web_portal/src/components/widgets/OpenOrders.tsx`

Tabela otwartych pozycji tradingowych.

```tsx
import OpenOrders from '@/components/widgets/OpenOrders'

<OpenOrders />
```

**Kolumny tabeli:**
- Para (symbol)
- Typ (LONG/SHORT badge)
- Rozmiar
- Wejście (entry price)
- Obecna (current price)
- P&L (profit/loss z procentem)
- Status (badge)
- Akcje (przycisk Zamknij)

**Funkcje:**
- Filtry: Wszystkie, Aktywne, Zamknięte
- Hover effect na wierszach
- Podsumowanie: Całkowity P&L, ROI, liczba pozycji
- Przycisk "Zamknij wszystkie"

**Typ danych:**
```typescript
interface Order {
  id: string
  symbol: string
  type: 'LONG' | 'SHORT'
  size: string
  entry: string
  current: string
  pnl: string
  pnlPercent: string
  status: string
}
```

---

## Komponenty Atomowe (do stworzenia)

### Button

```tsx
interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  icon?: React.ReactNode
  onClick?: () => void
  children: React.ReactNode
}

// Przykład użycia
<Button variant="primary" size="md" icon={<Play />}>
  Start Trading
</Button>
```

**Warianty:**
- `primary`: Teal background (#14b8a6)
- `secondary`: Dark background (#111c26)
- `danger`: Red background (#ef4444)

---

### Card

```tsx
interface CardProps {
  title?: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}

// Przykład użycia
<Card title="Market Overview" action={<Button>View All</Button>}>
  {/* Content */}
</Card>
```

---

### Badge

```tsx
interface BadgeProps {
  variant?: 'success' | 'danger' | 'warning' | 'info'
  children: React.ReactNode
}

// Przykład użycia
<Badge variant="success">LONG</Badge>
<Badge variant="danger">SHORT</Badge>
<Badge variant="info">Active</Badge>
```

---

### Input

```tsx
interface InputProps {
  label?: string
  type?: 'text' | 'number' | 'email' | 'password'
  placeholder?: string
  value: string
  onChange: (value: string) => void
  error?: string
}

// Przykład użycia
<Input
  label="Symbol"
  placeholder="BTC/USDT"
  value={symbol}
  onChange={setSymbol}
/>
```

---

### Select

```tsx
interface SelectProps {
  label?: string
  options: Array<{value: string, label: string}>
  value: string
  onChange: (value: string) => void
}

// Przykład użycia
<Select
  label="Timeframe"
  options={[
    {value: '1m', label: '1 minute'},
    {value: '5m', label: '5 minutes'},
  ]}
  value={timeframe}
  onChange={setTimeframe}
/>
```

---

## Utility Classes (Tailwind)

### Layout

```css
/* Containers */
.container              /* Centered container */
.flex                   /* Flexbox */
.grid                   /* Grid */
.grid-cols-12          /* 12 column grid */

/* Spacing */
.p-4, .p-6             /* Padding */
.m-4, .m-6             /* Margin */
.space-x-4             /* Horizontal spacing */
.space-y-4             /* Vertical spacing */
.gap-4                 /* Grid/flex gap */
```

### Colors

```css
/* Backgrounds */
.bg-rldc-dark-bg       /* #0a1219 */
.bg-rldc-dark-card     /* #111c26 */
.bg-rldc-teal-primary  /* #14b8a6 */

/* Text */
.text-slate-100        /* Primary text */
.text-slate-400        /* Secondary text */
.text-rldc-green-primary  /* Green text */
.text-rldc-red-primary    /* Red text */

/* Borders */
.border-rldc-dark-border  /* #1e2d3d */
```

### Typography

```css
/* Size */
.text-xs, .text-sm, .text-base, .text-lg, .text-xl, .text-2xl

/* Weight */
.font-normal, .font-medium, .font-semibold, .font-bold
```

### Effects

```css
/* Rounded corners */
.rounded-lg            /* 8px */
.rounded-full          /* Circle */

/* Shadows */
.shadow-md, .shadow-lg

/* Transitions */
.transition            /* All properties */
.hover:bg-rldc-teal-dark  /* Hover state */
```

---

## Hooks (do stworzenia)

### useMarketData

```tsx
const { data, loading, error } = useMarketData(symbol: string)

// Zwraca:
// data: MarketData | null
// loading: boolean
// error: Error | null
```

### useTradingMode

```tsx
const { mode, setMode, isLive, isDemo, isBacktest } = useTradingMode()

// Zwraca:
// mode: 'live' | 'demo' | 'backtest'
// setMode: (mode) => void
// isLive: boolean
// isDemo: boolean
// isBacktest: boolean
```

### useWebSocket

```tsx
const { connected, subscribe, unsubscribe } = useWebSocket(url: string)

// Zwraca:
// connected: boolean
// subscribe: (channel: string, callback: Function) => void
// unsubscribe: (channel: string) => void
```

---

## Wzorce

### Fetch i Display Data

```tsx
'use client'

import { useState, useEffect } from 'react'

export default function MyWidget() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchData() {
      try {
        const response = await fetch('/api/market/data')
        const json = await response.json()
        setData(json)
      } catch (error) {
        console.error('Error fetching data:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [])

  if (loading) return <div>Loading...</div>
  if (!data) return <div>No data</div>

  return (
    <div className="bg-rldc-dark-card rounded-lg p-6">
      {/* Render data */}
    </div>
  )
}
```

### Conditional Styling

```tsx
<div className={`
  px-2 py-1 rounded text-xs font-medium
  ${type === 'LONG' 
    ? 'bg-rldc-green-primary/20 text-rldc-green-primary'
    : 'bg-rldc-red-primary/20 text-rldc-red-primary'
  }
`}>
  {type}
</div>
```

### Event Handlers

```tsx
const handleClick = () => {
  // Logic
}

<button
  onClick={handleClick}
  className="bg-rldc-teal-primary hover:bg-rldc-teal-dark text-white px-4 py-2 rounded-lg transition"
>
  Click me
</button>
```

---

## Testowanie

### Unit Tests (przykład)

```tsx
import { render, screen } from '@testing-library/react'
import MarketOverview from '@/components/widgets/MarketOverview'

describe('MarketOverview', () => {
  it('renders market cards', () => {
    render(<MarketOverview />)
    expect(screen.getByText('BTC/USDT')).toBeInTheDocument()
    expect(screen.getByText('ETH/USDT')).toBeInTheDocument()
  })
})
```

---

## Performance

### Optymalizacja Renderowania

```tsx
import { memo } from 'react'

const ExpensiveComponent = memo(({ data }) => {
  // Expensive rendering logic
  return <div>{/* ... */}</div>
})
```

### Lazy Loading

```tsx
import dynamic from 'next/dynamic'

const TradingView = dynamic(() => import('@/components/widgets/TradingView'), {
  loading: () => <p>Loading chart...</p>,
  ssr: false
})
```

---

## Najlepsze Praktyki

1. **Używaj TypeScript** dla wszystkich komponentów
2. **Ekstrahuj logikę** do custom hooks
3. **Komponenty atomowe** - małe, wielokrotnego użytku
4. **Props validation** - zawsze definiuj typy props
5. **Accessibility** - używaj semantycznego HTML i ARIA labels
6. **Performance** - używaj memo, useMemo, useCallback gdy potrzeba
7. **Testowanie** - minimum smoke tests dla każdego komponentu
8. **Dokumentacja** - dodaj JSDoc komentarze do komponentów

---

**Wersja:** 1.0  
**Ostatnia aktualizacja:** 31 stycznia 2026
