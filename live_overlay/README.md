# RLdC LIVE Overlay BOT SYNC

Overlay wygląda jak przesłany HTML: boczne menu, nagłówek, aktywne pary, wykres, Analiza AI i dolne karty.

Najważniejsze: dane są pobierane z bota przez lokalny adapter `/overlay/api/live-state`. Jeśli backend nie zwraca danych, overlay pokazuje błąd/brak danych i nie zmyśla wyników.

Stały czerwony komunikat: `FAZA TESTÓW I DOSTRAJANIA — AKTUALNE DANE MOGĄ BYĆ NIEKOMPLETNE LUB BŁĘDNE`.

## Instalacja

```bash
chmod +x install_rldc_live_overlay_bot_sync.sh
./install_rldc_live_overlay_bot_sync.sh
cd /home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/live_overlay
./start_live_overlay.sh
```

## OBS

URL: `http://127.0.0.1:8099/index.html`
Width: `1920`
Height: `1080`

## Backend

Domyślnie: `http://127.0.0.1:8000`

Inny backend:

```bash
RLDC_BACKEND_URL=http://127.0.0.1:8000 ./start_live_overlay.sh
```
