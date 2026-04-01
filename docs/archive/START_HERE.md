# START HERE — RLdC AiNalyzator

> Ten plik jest pierwszym dokumentem, który należy przeczytać po otwarciu projektu.

---

## Szybki start (po restarcie VS Code lub systemu)

```bash
cd /home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator
bash scripts/start_dev.sh
```

Skrypt sam:
- sprawdzi, czy procesy już działają,
- uruchomi backend (port 8000) i frontend (port 3000),
- odczeka 10 sekund i zweryfikuje dostępność.

---

## Adresy dostępowe

| Gdzie | Adres |
|---|---|
| Aplikacja (lokalnie) | http://localhost:3000 |
| Aplikacja (z sieci LAN) | http://192.168.0.109:3000 |
| Backend API | http://192.168.0.109:8000 |
| Dokumentacja API | http://localhost:8000/docs |

---

## Sprawdzenie stanu systemu

```bash
bash scripts/status_dev.sh
```

Wyświetli:
- czy porty 8000 i 3000 są zajęte,
- czy kluczowe endpointy zwracają HTTP 200.

---

## Zatrzymanie procesów

```bash
bash scripts/stop_dev.sh
```

---

## Co zrobić po restarcie VS Code

VS Code **nie uruchamia automatycznie** backendu ani frontendu.  
Po każdym otwarciu projektu trzeba ręcznie wywołać:

```bash
bash scripts/start_dev.sh
```

> **Uwaga:** Jeśli procesy już działają (uruchomione z poprzedniej sesji terminala),  
> skrypt to wykryje i nie uruchomi duplikatów.

---

## Ręczne uruchamianie (bez skryptu)

### Backend
```bash
cd /home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator
.venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd /home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/web_portal
npx next dev --hostname 0.0.0.0 --port 3000
```

---

## Logi

Po uruchomieniu przez `start_dev.sh` logi trafiają do:

```
logs/dev/backend.log
logs/dev/frontend.log
```

Podgląd na żywo:
```bash
tail -f logs/dev/backend.log
tail -f logs/dev/frontend.log
```

---

## Struktura projektu

| Katalog | Co robi |
|---|---|
| `backend/` | FastAPI — API, kolektor, analiza, baza danych |
| `web_portal/` | Next.js 14 — interfejs użytkownika |
| `telegram_bot/` | Bot Telegram z 18 komendami |
| `tests/` | Testy smoke (175/175 ✅) |
| `scripts/` | Skrypty startowe |
| `docs/` | Raporty audytu i dokumentacja |

---

## Wymagania

- Python 3.10+ z `.venv` (wirtualne środowisko w katalogu projektu)
- Node.js 18+ z zainstalowanymi `node_modules` w `web_portal/`

### Pierwsze uruchomienie na nowej maszynie

```bash
# 1. Wirtualne środowisko Python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Zależności Node.js
cd web_portal
npm install
cd ..

# 3. Start
bash scripts/start_dev.sh
```

---

## Zmienne środowiskowe

Plik `.env` w katalogu głównym (nie jest commitowany do git):

```env
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
ADMIN_TOKEN=...
OPENAI_API_KEY=...       # opcjonalnie — bez tego działa tryb heurystyczny
```

Plik `web_portal/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://192.168.0.109:8000
```

---

*Dokumentacja: RLdC AiNalyzator v0.7-beta | Data: 2026-03-28*
