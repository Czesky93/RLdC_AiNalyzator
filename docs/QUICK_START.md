# RLDC AiNalyzer - Quick Start Guide

## Szybki Start dla Deweloperów

### Wymagania

- **Node.js** 18.x lub nowszy
- **npm** 9.x lub nowszy
- **Git** 2.x lub nowszy

### Instalacja i Uruchomienie Web Portal

```bash
# 1. Sklonuj repozytorium
git clone https://github.com/Czesky93/RLdC_AiNalyzator.git
cd RLdC_AiNalyzator

# 2. Przejdź do folderu web_portal
cd web_portal

# 3. Zainstaluj zależności
npm install

# 4. Uruchom w trybie deweloperskim
npm run dev
```

Aplikacja będzie dostępna pod adresem: **http://localhost:3000**

### Build Produkcyjny

```bash
# Build
npm run build

# Uruchom produkcyjną wersję
npm start
```

### Struktura Projektu

```
web_portal/
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── layout.tsx          # Root layout
│   │   └── page.tsx            # Home page
│   ├── components/             # React components
│   │   ├── Dashboard.tsx       # Main dashboard
│   │   ├── Topbar.tsx          # Top navigation
│   │   ├── Sidebar.tsx         # Side menu
│   │   ├── MainContent.tsx     # Content area
│   │   └── widgets/            # Dashboard widgets
│   │       ├── MarketOverview.tsx
│   │       ├── TradingView.tsx
│   │       ├── OpenOrders.tsx
│   │       └── MarketInsights.tsx
│   └── styles/
│       └── globals.css         # Global styles
├── package.json
├── tsconfig.json
├── tailwind.config.js
└── next.config.js
```

## Dodawanie Nowego Komponentu

### 1. Stwórz plik komponentu

```bash
# W folderze components
touch src/components/MyComponent.tsx
```

### 2. Bazowy template komponentu

```tsx
'use client'

import React from 'react'

interface MyComponentProps {
  title: string
  data?: any
}

export default function MyComponent({ title, data }: MyComponentProps) {
  return (
    <div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border">
      <h2 className="text-lg font-semibold mb-4 text-slate-200">{title}</h2>
      
      {/* Your content here */}
      <div className="text-slate-400">
        Component content
      </div>
    </div>
  )
}
```

### 3. Użyj komponentu

```tsx
import MyComponent from '@/components/MyComponent'

export default function Page() {
  return (
    <MyComponent title="My Custom Component" />
  )
}
```

## Stylowanie

### Używaj Tailwind CSS

```tsx
// ✅ Dobrze - używaj utility classes
<div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border">
  <h2 className="text-lg font-semibold text-slate-200">Title</h2>
</div>

// ❌ Unikaj inline styles
<div style={{ backgroundColor: '#111c26', padding: '24px' }}>
  <h2 style={{ fontSize: '18px' }}>Title</h2>
</div>
```

### Custom klasy w globals.css

```css
/* src/styles/globals.css */

.custom-gradient {
  background: linear-gradient(135deg, #14b8a6 0%, #0f766e 100%);
}

.custom-animation {
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
```

## Kolory Design System

### Używaj zdefiniowanych kolorów

```tsx
// Tła
className="bg-rldc-dark-bg"         // #0a1219
className="bg-rldc-dark-card"       // #111c26

// Akcenty
className="text-rldc-teal-primary"  // #14b8a6
className="text-rldc-green-primary" // #10b981
className="text-rldc-red-primary"   // #ef4444

// Tekst
className="text-slate-100"          // Primary text
className="text-slate-400"          // Secondary text

// Obramowania
className="border-rldc-dark-border" // #1e2d3d
```

## Ikony

### Import z Lucide React

```tsx
import { TrendingUp, AlertCircle, Settings } from 'lucide-react'

export default function MyComponent() {
  return (
    <div>
      <TrendingUp size={20} className="text-rldc-green-primary" />
      <AlertCircle size={20} className="text-yellow-500" />
      <Settings size={20} className="text-slate-400" />
    </div>
  )
}
```

## Wykresy

### Używaj Recharts

```tsx
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

const data = [
  { time: '00:00', price: 20100 },
  { time: '04:00', price: 20300 },
  // ...
]

export default function Chart() {
  return (
    <ResponsiveContainer width="100%" height={400}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2d3d" />
        <XAxis dataKey="time" stroke="#64748b" />
        <YAxis stroke="#64748b" />
        <Tooltip
          contentStyle={{
            backgroundColor: '#111c26',
            border: '1px solid #1e2d3d',
            borderRadius: '8px'
          }}
        />
        <Line 
          type="monotone" 
          dataKey="price" 
          stroke="#14b8a6" 
          strokeWidth={2}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
```

## State Management

### useState dla lokalnego stanu

```tsx
'use client'

import { useState } from 'react'

export default function Counter() {
  const [count, setCount] = useState(0)

  return (
    <button onClick={() => setCount(count + 1)}>
      Count: {count}
    </button>
  )
}
```

### useEffect dla efektów ubocznych

```tsx
'use client'

import { useState, useEffect } from 'react'

export default function DataFetcher() {
  const [data, setData] = useState(null)

  useEffect(() => {
    async function fetchData() {
      const response = await fetch('/api/data')
      const json = await response.json()
      setData(json)
    }

    fetchData()
  }, []) // Empty array = run once on mount

  return <div>{data ? JSON.stringify(data) : 'Loading...'}</div>
}
```

## Responsywność

### Mobile-First Approach

```tsx
<div className="
  grid
  grid-cols-1          /* Mobile: 1 kolumna */
  md:grid-cols-2       /* Tablet: 2 kolumny */
  lg:grid-cols-4       /* Desktop: 4 kolumny */
  gap-4
">
  {/* Cards */}
</div>
```

### Breakpoints

- `sm`: 640px
- `md`: 768px
- `lg`: 1024px
- `xl`: 1280px
- `2xl`: 1536px

## Dodawanie Nowego Widoku

### 1. Dodaj do Sidebar

```tsx
// src/components/Sidebar.tsx

const menuItems = [
  // ... existing items
  { id: 'my-view', label: 'Mój Widok', icon: Star },
]
```

### 2. Stwórz komponent widoku

```tsx
// src/components/views/MyView.tsx

export default function MyView() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">Mój Widok</h1>
      {/* Content */}
    </div>
  )
}
```

### 3. Dodaj routing w MainContent

```tsx
// src/components/MainContent.tsx

import MyView from './views/MyView'

export default function MainContent({ activeView, tradingMode }) {
  if (activeView === 'my-view') {
    return <MyView />
  }
  
  // ... other views
}
```

## Debugowanie

### React DevTools

```bash
# Chrome Extension
https://chrome.google.com/webstore/detail/react-developer-tools/fmkadmapgofadopljbjfkapdkoienihi
```

### Console Logging

```tsx
console.log('Debug:', data)
console.error('Error:', error)
console.warn('Warning:', warning)
```

### Next.js Dev Tools

Dostępne automatycznie w trybie development (ikona w prawym dolnym rogu strony).

## Typowe Problemy

### Problem: "Cannot find module '@/components/...'"

**Rozwiązanie:** Sprawdź `tsconfig.json`:

```json
{
  "compilerOptions": {
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

### Problem: Style Tailwind nie działają

**Rozwiązanie:** 
1. Sprawdź `tailwind.config.js` - czy content paths są poprawne
2. Sprawdź czy `globals.css` importuje `@tailwind` directives
3. Restart dev server

### Problem: Komponenty nie re-renderują się

**Rozwiązanie:**
- Sprawdź czy używasz `'use client'` w komponentach ze stanem
- Sprawdź dependencies w `useEffect`
- Użyj React DevTools do śledzenia props

## Wydajność

### Optymalizacja Obrazów

```tsx
import Image from 'next/image'

<Image
  src="/images/logo.png"
  alt="Logo"
  width={200}
  height={50}
  priority // Dla ważnych obrazów
/>
```

### Code Splitting

```tsx
import dynamic from 'next/dynamic'

const HeavyComponent = dynamic(() => import('./HeavyComponent'), {
  loading: () => <p>Loading...</p>,
  ssr: false
})
```

### Memo dla drogich komponentów

```tsx
import { memo } from 'react'

const ExpensiveList = memo(({ items }) => {
  return (
    <ul>
      {items.map(item => <li key={item.id}>{item.name}</li>)}
    </ul>
  )
})
```

## Testing (TODO)

```bash
# Zainstaluj testing libraries
npm install --save-dev @testing-library/react @testing-library/jest-dom jest

# Uruchom testy
npm test
```

## Deployment (TODO)

### Vercel (Recommended dla Next.js)

```bash
npm install -g vercel
vercel
```

### Docker

```dockerfile
# Dockerfile (przykład)
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
CMD ["npm", "start"]
```

## Dodatkowe Zasoby

- **Next.js Docs**: https://nextjs.org/docs
- **Tailwind CSS**: https://tailwindcss.com/docs
- **Recharts**: https://recharts.org/
- **Lucide Icons**: https://lucide.dev/icons
- **Design System**: [docs/DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md)
- **Component Library**: [docs/COMPONENT_LIBRARY.md](./COMPONENT_LIBRARY.md)

## Pomoc

Jeśli masz pytania lub problemy:
1. Sprawdź dokumentację w `docs/`
2. Zobacz przykłady w istniejących komponentach
3. Otwórz issue na GitHub

---

**Happy Coding! 🚀**
