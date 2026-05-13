# RLDC AiNalyzer - System Projektowania (Design System)

## Przegląd

Ten dokument definiuje kompletny system projektowania dla platformy RLDC AiNalyzer. Został stworzony w oparciu o szablony graficzne znajdujące się w folderze `web_portal/`.

## Paleta Kolorów

### Tło i Karty

```css
/* Główne tło aplikacji */
--bg-dark: #0a1219
--rldc-dark-bg: #0a1219

/* Tło kart i paneli */
--card-bg: #111c26
--rldc-dark-card: #111c26

/* Hover state dla elementów */
--rldc-dark-hover: #1a2730
```

### Obramowania

```css
/* Główny kolor obramowań */
--border-color: #1e2d3d
--rldc-dark-border: #1e2d3d
```

### Kolory Akcentowe - Teal/Cyan

```css
/* Główny kolor akcentowy */
--teal-primary: #14b8a6
--rldc-teal-primary: #14b8a6

/* Jasniejsza wersja */
--rldc-teal-light: #2dd4bf

/* Ciemniejsza wersja */
--rldc-teal-dark: #0f766e
```

### Kolory Akcentowe - Zielony (Wzrosty)

```css
--green-primary: #10b981
--rldc-green-primary: #10b981
--rldc-green-light: #34d399
```

### Kolory Akcentowe - Czerwony (Spadki/Alerty)

```css
--red-primary: #ef4444
--rldc-red-primary: #ef4444
--rldc-red-light: #f87171
```

### Tekst

```css
/* Główny tekst */
--text-primary: #f1f5f9

/* Tekst drugorzędny */
--text-secondary: #cbd5e1
--text-muted: #64748b

/* Tekst nieaktywny */
--text-disabled: #475569
```

## Typografia

### Font Family

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen',
  'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue',
  sans-serif;
```

### Rozmiary Czcionek

```css
/* Nagłówki */
--text-3xl: 1.875rem    /* H1 */
--text-2xl: 1.5rem      /* H2 */
--text-xl: 1.25rem      /* H3 */
--text-lg: 1.125rem     /* H4 */

/* Tekst podstawowy */
--text-base: 1rem       /* 16px */
--text-sm: 0.875rem     /* 14px */
--text-xs: 0.75rem      /* 12px */
```

### Wagi Czcionek

```css
--font-normal: 400
--font-medium: 500
--font-semibold: 600
--font-bold: 700
```

## Odstępy (Spacing)

```css
--space-1: 0.25rem    /* 4px */
--space-2: 0.5rem     /* 8px */
--space-3: 0.75rem    /* 12px */
--space-4: 1rem       /* 16px */
--space-6: 1.5rem     /* 24px */
--space-8: 2rem       /* 32px */
--space-12: 3rem      /* 48px */
```

## Zaokrąglenia (Border Radius)

```css
--radius-sm: 4px
--radius-md: 8px
--radius-lg: 12px
--radius-xl: 16px
--radius-full: 9999px
```

## Cienie (Shadows)

```css
--shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.5);
--shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.5);
--shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.5);
```

## Komponenty UI

### Przyciski

#### Przycisk Podstawowy (Teal)
```css
background: #14b8a6
color: #ffffff
padding: 0.5rem 1rem
border-radius: 8px
font-weight: 500
transition: background 0.2s

hover:
  background: #0f766e
```

#### Przycisk Niebezpieczny (Czerwony)
```css
background: #ef4444
color: #ffffff
padding: 0.5rem 1rem
border-radius: 8px
font-weight: 500

hover:
  background: #dc2626
```

#### Przycisk Drugorzędny
```css
background: #111c26
color: #64748b
padding: 0.5rem 1rem
border-radius: 8px

hover:
  background: #1a2730
  color: #cbd5e1
```

### Karty (Cards)

```css
background: #111c26
border: 1px solid #1e2d3d
border-radius: 8px
padding: 1.5rem

hover:
  border-color: rgba(20, 184, 166, 0.5)
```

### Tabele

#### Nagłówek
```css
border-bottom: 1px solid #1e2d3d
color: #64748b
font-size: 0.75rem
font-weight: 500
padding-bottom: 0.75rem
```

#### Wiersz
```css
border-bottom: 1px solid rgba(30, 45, 61, 0.5)
padding: 0.75rem 0

hover:
  background: #1a2730
```

### Odznaki (Badges)

#### Status Aktywny
```css
background: rgba(20, 184, 166, 0.2)
color: #14b8a6
padding: 0.25rem 0.5rem
border-radius: 4px
font-size: 0.75rem
font-weight: 500
```

#### Long Position
```css
background: rgba(16, 185, 129, 0.2)
color: #10b981
```

#### Short Position
```css
background: rgba(239, 68, 68, 0.2)
color: #ef4444
```

### Formularz

#### Input
```css
background: #0a1219
border: 1px solid #1e2d3d
border-radius: 8px
color: #f1f5f9
padding: 0.5rem 0.75rem

focus:
  border-color: #14b8a6
  outline: none
```

#### Select/Dropdown
```css
/* Jak input, plus: */
appearance: none
background-image: url("data:image/svg+xml,...") /* strzałka w dół */
```

### Pasek Postępu (Progress Bar)

```css
/* Kontener */
background: #1e2d3d
height: 0.375rem
border-radius: 9999px

/* Wypełnienie */
background: #14b8a6
height: 100%
border-radius: 9999px
```

## Layout

### Topbar
```
Wysokość: 4rem (64px)
Background: #111c26
Border-bottom: 1px solid #1e2d3d
Padding: 0 1.5rem

Zawiera:
- Logo RLDC (po lewej)
- Nawigacja główna
- Przełącznik trybu (DEMO/LIVE/BACKTEST)
- Przycisk STOP TRADING
- Ikona alertów
```

### Sidebar
```
Szerokość: 16rem (256px)
Background: #111c26
Border-right: 1px solid #1e2d3d
Padding: 1rem

Menu items:
- Padding: 0.75rem 1rem
- Border-radius: 8px
- Aktywny: border-left 2px #14b8a6, bg rgba(20, 184, 166, 0.1)
```

### Grid Dashboard
```css
/* Główny kontener */
padding: 1.5rem
display: grid
grid-template-columns: repeat(12, 1fr)
gap: 1rem

/* Breakpoints */
sm: 640px
md: 768px
lg: 1024px
xl: 1280px
2xl: 1536px
```

## Ikony

Używamy **Lucide React** dla wszystkich ikon:
- Rozmiar domyślny: 20px
- Rozmiar mały: 16px
- Rozmiar duży: 24px
- Kolor: dziedziczy z rodzica

Przykłady często używanych ikon:
- TrendingUp / TrendingDown (wzrosty/spadki)
- AlertCircle / AlertTriangle (alerty)
- Activity (sygnały AI)
- BarChart3 (wykresy)
- Power (stop trading)
- Settings (ustawienia)

## Wykresy (Charts)

Używamy **Recharts** z następującymi ustawieniami:

```javascript
// Tło siatki
<CartesianGrid strokeDasharray="3 3" stroke="#1e2d3d" />

// Osie
<XAxis stroke="#64748b" style={{ fontSize: '12px' }} />
<YAxis stroke="#64748b" style={{ fontSize: '12px' }} />

// Tooltip
<Tooltip
  contentStyle={{
    backgroundColor: '#111c26',
    border: '1px solid #1e2d3d',
    borderRadius: '8px',
    color: '#f1f5f9'
  }}
/>

// Linie/Area
stroke="#14b8a6"
strokeWidth={2}
fill="url(#gradientTeal)" /* gradient od #14b8a6 do transparent */
```

## Animacje i Przejścia

```css
/* Standardowe przejście */
transition: all 0.2s ease

/* Hover states */
transition: background-color 0.2s, color 0.2s, border-color 0.2s

/* Fade in */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
```

## Scrollbar

```css
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #0a1219;
}

::-webkit-scrollbar-thumb {
  background: #1e2d3d;
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: #2a3f52;
}
```

## Responsywność

### Mobile First Approach

```css
/* Mobile (default) */
padding: 1rem
font-size: 0.875rem

/* Tablet (md: 768px) */
@media (min-width: 768px) {
  padding: 1.5rem
  font-size: 1rem
}

/* Desktop (lg: 1024px) */
@media (min-width: 1024px) {
  /* Full layout z sidebar */
}
```

### Breakpoints w Tailwind

```javascript
sm: '640px'
md: '768px'
lg: '1024px'
xl: '1280px'
'2xl': '1536px'
```

## Najlepsze Praktyki

### 1. Spójność Kolorów
- Używaj tylko zdefiniowanych kolorów z palety
- Teal (#14b8a6) dla głównych akcji
- Zielony (#10b981) dla wzrostów/zysków
- Czerwony (#ef4444) dla spadków/strat/alertów

### 2. Hierarchia Wizualna
- H1: główny tytuł strony (text-2xl, font-bold)
- H2: tytuły sekcji (text-lg, font-semibold)
- H3: tytuły kart (text-sm, font-semibold)
- Tekst: text-sm dla większości tekstu

### 3. Odstępy
- Konsekwentnie używaj wielokrotności 4px (0.25rem)
- Padding kart: 1.5rem (24px)
- Gap w gridzie: 1rem (16px)
- Margin między sekcjami: 1.5rem - 2rem

### 4. Dostępność
- Kontrast tekstu minimum 4.5:1
- Wszystkie interaktywne elementy mają hover state
- Focus states dla nawigacji klawiaturą
- Semantyczny HTML (nav, main, section, article)

### 5. Performance
- Lazy loading dla obrazów
- Code splitting dla różnych widoków
- Minimalizacja re-renderów React
- Optymalizacja bundle size

## Przykłady Użycia

### Karta z danymi rynkowymi

```jsx
<div className="bg-rldc-dark-card rounded-lg p-6 border border-rldc-dark-border hover:border-rldc-teal-primary/50 transition">
  <div className="flex items-center justify-between mb-2">
    <span className="text-sm font-medium text-slate-400">BTC/USDT</span>
    <TrendingUp size={16} className="text-rldc-green-primary" />
  </div>
  <div className="text-2xl font-bold text-slate-100 mb-1">
    €20,587
  </div>
  <div className="text-sm text-rldc-green-primary">
    +71,981 (+3.6%)
  </div>
</div>
```

### Przycisk akcji

```jsx
<button className="flex items-center space-x-2 bg-rldc-teal-primary hover:bg-rldc-teal-dark text-white px-4 py-2 rounded-lg text-sm font-medium transition">
  <Play size={16} />
  <span>Start Trading</span>
</button>
```

### Wiersz tabeli

```jsx
<tr className="border-b border-rldc-dark-border/50 hover:bg-rldc-dark-hover transition">
  <td className="py-3 text-sm font-medium text-slate-200">BTC/USDT</td>
  <td className="py-3">
    <span className="px-2 py-1 rounded text-xs font-medium bg-rldc-green-primary/20 text-rldc-green-primary">
      LONG
    </span>
  </td>
  {/* ... */}
</tr>
```

## Rozszerzenia Tailwind

W `tailwind.config.js`:

```javascript
module.exports = {
  theme: {
    extend: {
      colors: {
        'rldc-dark': {
          bg: '#0a1219',
          card: '#111c26',
          border: '#1e2d3d',
          hover: '#1a2730',
        },
        'rldc-teal': {
          primary: '#14b8a6',
          light: '#2dd4bf',
          dark: '#0f766e',
        },
        'rldc-green': {
          primary: '#10b981',
          light: '#34d399',
        },
        'rldc-red': {
          primary: '#ef4444',
          light: '#f87171',
        },
      },
    },
  },
}
```

## Wersjonowanie

**Wersja:** 1.0  
**Data utworzenia:** 31 stycznia 2026  
**Ostatnia aktualizacja:** 31 stycznia 2026  
**Oparte na:** Szablony graficzne w `web_portal/` (PNG files)

## Wsparcie

Dla pytań dotyczących design systemu, zobacz:
- `web_portal/README.md` - dokumentacja web portalu
- `web_portal/src/styles/globals.css` - globalne style CSS
- `web_portal/tailwind.config.js` - konfiguracja Tailwind
