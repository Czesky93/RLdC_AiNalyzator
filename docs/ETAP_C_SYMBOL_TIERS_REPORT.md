# ETAP C — System Tierów Symboli (Account-Specific Strategy)

**Data:** 2026-03-26 → aktualizacja 2026-04-01  
**Testy:** 181/181 PASSED  
**Zmienione pliki:** `backend/runtime_settings.py`, `backend/collector.py`, `.env`, `tests/test_smoke.py`

---

## 1. Snapshot konta Binance

| Aktywo | Ilość | Wartość EUR | Udział |
|--------|-------|-------------|--------|
| WLFI (Earn) | 3 260 | 275.67 | 99.4% |
| SHIB2 (Earn) | 297 379 | 1.53 | 0.6% |
| BTC (Earn) | 0.0000252 | 1.51 | 0.5% |
| ETH (Earn) | 0.0000352 | 0.06 | <0.1% |
| SOL (Earn) | 0.00042 | 0.03 | <0.1% |
| ETC (Earn) | 0.00032 | 0.01 | <0.1% |
| BNB (Earn) | 0.00000001 | ~0 | ~0% |
| EUR (free) | 0.01 | 0.01 | ~0% |
| **SUMA** | — | **~277.29** | 100% |

**Kluczowe fakty:**
- EUR free = 0.01 → bot **nie ma płynnego kapitału** do handlu
- Wszystkie aktywa w Simple Earn (LD*), `canRedeem=True`, `freeAmount=0`
- WLFI = 99.4% portfela — dominacja jednego spekulacyjnego tokenu
- Bot działa w trybie DEMO (wirtualny balans: `DEMO_INITIAL_BALANCE`)

---

## 2. Zaprojektowany system tierów

### Architektura

```
runtime_settings.py   →   symbol_tiers (SettingSpec, JSON)
                               ↓
                        build_symbol_tier_map()
                               ↓
collector.py          →   tier_map w _load_trading_config() → tc dict
                               ↓
                        _screen_entry_candidates() per-symbol:
                          1. Tier gating (brak tieru → SKIP)
                          2. Tier daily trade limit
                          3. min_confidence += tier.min_confidence_add
                          4. min_edge_multiplier += tier.min_edge_multiplier_add
                          5. risk_scale *= tier.risk_scale
                          6. Telegram msg z [TIER_NAME]
```

### Konfiguracja tierów

| Tier | Symbole | min_confidence_add | min_edge_multiplier_add | risk_scale | max_trades/dzień/sym |
|------|---------|--------------------|----|-----|------|
| **CORE** | BTCEUR, BTCUSDC, ETHEUR, ETHUSDC, SOLEUR, SOLUSDC, BNBEUR, BNBUSDC | +0.00 | +0.00 | ×1.0 | 10 |
| **ALTCOIN** | ETCUSDC, SHIBEUR, SHIBUSDC, SXTUSDC | +0.05 | +0.50 | ×0.7 | 3 |
| **SPECULATIVE** | WLFIEUR, WLFIUSDC | +0.10 | +1.00 | ×0.3 | 2 |

> **HOLD tier** usunięty (2026-04-01). WLFIEUR przeniesiony do SPECULATIVE — pełne uczestnictwo w tradingu z podwyższonymi progami.

### Efektywne parametry (bazowe: conf=0.75, edge=2.5)

| Symbol | Tier | Efektywne min_confidence | Efektywne min_edge | Efektywny risk_scale |
|--------|------|--------------------------|---------------------|----------------------|
| BTCEUR | CORE | 0.75 | 2.5 | 1.0 |
| ETHEUR | CORE | 0.75 | 2.5 | 1.0 |
| SOLEUR | CORE | 0.75 | 2.5 | 1.0 |
| BNBEUR | CORE | 0.75 | 2.5 | 1.0 |
| BTCUSDC | CORE | 0.75 | 2.5 | 1.0 |
| ETHUSDC | CORE | 0.75 | 2.5 | 1.0 |
| SOLUSDC | CORE | 0.75 | 2.5 | 1.0 |
| BNBUSDC | CORE | 0.75 | 2.5 | 1.0 |
| ETCUSDC | ALTCOIN | 0.80 | 3.0 | 0.7 |
| SHIBEUR | ALTCOIN | 0.80 | 3.0 | 0.7 |
| SHIBUSDC | ALTCOIN | 0.80 | 3.0 | 0.7 |
| SXTUSDC | ALTCOIN | 0.80 | 3.0 | 0.7 |
| WLFIEUR | SPECULATIVE | 0.85 | 3.5 | 0.3 |
| WLFIUSDC | SPECULATIVE | 0.85 | 3.5 | 0.3 |

---

## 3. Zmiany w kodzie

### `backend/runtime_settings.py`
- Dodano `SettingSpec("symbol_tiers")` — konfiguracja JSON z domyślnymi tierami
- Dodano `build_symbol_tier_map(tiers_config)` — buduje lookup `symbol → overrides`
- Dodano stałą `_TIER_DEFAULTS` z wartościami domyślnymi

### `backend/collector.py`
- Import: dodano `build_symbol_tier_map`
- `_load_trading_config()`: buduje `tier_map` i dodaje do zwracanego `tc` dict
- `_screen_entry_candidates()`:
  - Pobiera `tier_map` z `tc`
  - **Tier gating**: symbol bez tieru → SKIP (`symbol_not_in_any_tier`)
  - **Dzienny limit transakcji per symbol** z tieru → SKIP (`tier_daily_trade_limit`)
  - **min_confidence override**: `min_confidence += tier.min_confidence_add` (cap 1.0)
  - **min_edge_multiplier override**: `effective_edge_mult = base + tier_add`
  - **risk_scale override**: `risk_scale *= tier_risk_scale`
  - **Telegram msg**: `[TIER_NAME]` w tytule wiadomości
  - **Decision trace**: tier info w `details` i `risk_check`

### `.env`
- Rozszerzono `WATCHLIST` z 3 do 13 symboli (6×EUR + 6×USDC + SXT/USDC)

---

## 4. Nowe reason_codes w decision trace

| Reason Code | Opis |
|-------------|------|
| `symbol_not_in_any_tier` | Symbol nie należy do żadnego tieru — pominięty |
| `tier_daily_trade_limit` | Osiągnięto dzienny limit transakcji z tieru |

---

## 5. Konfigurowalaność

Tiery można zmieniać:
1. **ENV**: `SYMBOL_TIERS='{"CORE": {...}, ...}'`
2. **DB override**: klucz `symbol_tiers` w tabeli `RuntimeSetting`
3. **API**: `PATCH /api/config` z kluczem `symbol_tiers`

Każdy tier ma 4 parametry:
- `symbols` — lista symboli
- `min_confidence_add` — dodatkowe min_confidence (addytywne)
- `min_edge_multiplier_add` — dodatkowe min_edge (addytywne)
- `risk_scale` — mnożnik rozmiaru pozycji (multiplikatywny)
- `max_trades_per_day_per_symbol` — dzienny limit transakcji

---

## 6. Strategiczne rekomendacje

### Realna sytuacja konta
- Konto ma **0.01 EUR wolnego kapitału** — niewystarczające do handlu
- Bot działa w trybie **DEMO** (symulacja z wirtualnym saldem)
- Aby handlować realnie: zredeemuj aktywa z Earn lub wpłać EUR

### Co robi ten system
- **Nie-trade jako default**: symbol bez tieru = SKIP
- **Kwarantanna WLFI**: 99.4% portfela, ale bot traktuje go z najostrzejszymi filtrami
- **CORE 4 symbole**: BTC/ETH/SOL/BNB — pełne zaufanie, standardowe parametry
- **SECONDARY ETC**: bardziej restrykcyjny niż CORE, mniej niż QUARANTINE

### Pliki zmienione
1. [backend/runtime_settings.py](backend/runtime_settings.py) — +40 linii (SettingSpec + helper)
2. [backend/collector.py](backend/collector.py) — +35 linii netto (tier gating + overrides)
3. [.env](.env) — watchlist rozszerzony

### Testy: 171/171 PASSED ✅
