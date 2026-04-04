# Publiczny dostęp do RLdC AiNalyzer — instrukcja wdrożenia

## 1. Lokalnie (LAN)

Panel już działa lokalnie. Możesz wejść z każdego urządzenia w sieci:

```
http://192.168.0.109:3000        ← frontend
http://192.168.0.109:8000        ← backend API
```

Sprawdź IP swojego serwera:
```bash
ip a | grep inet
```

---

## 2. DS-Lite / brak publicznego IPv4

Twój router ma DS-Lite (IPv6 + CGNAT IPv4), co oznacza:
- **klasyczny port forwarding IPv4 NIE zadziała**,
- musisz użyć tunelu lub domeny z reverse proxy.

### 2A. Tunel Cloudflare (BEZPŁATNY, zalecany)

Cloudflare Tunnel nie wymaga publicznego IPv4.

```bash
# Instalacja cloudflared (Debian/Ubuntu)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# Szybki tunel bez konta (tymczasowy URL)
cloudflared tunnel --url http://localhost:3000

# Output: https://xxxx.trycloudflare.com  ← skopiuj ten URL
```

Po uzyskaniu URL ustaw w `.env`:
```env
CLOUDFLARE_TUNNEL_URL=https://xxxx.trycloudflare.com
```

**Stały tunel (z kontem Cloudflare):**
```bash
cloudflared tunnel login
cloudflared tunnel create rldc-panel
cloudflared tunnel route dns rldc-panel twoja-domena.pl
# Uruchom z config file — patrz: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
```

### 2B. Tunel ngrok

```bash
# Instalacja
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok

# Uruchom
ngrok http 3000

# Ustaw w .env:
# NGROK_URL=https://xxxx.ngrok.io
```

### 2C. VPS + reverse proxy (opcja trwała)

Jeśli masz VPS z publicznym IPv4:
1. Na VPS zainstaluj Nginx,
2. Skonfiguruj reverse proxy na Twój domowy serwer przez SSH tunnel.

```bash
# Na serwerze domowym — SSH reverse tunnel do VPS
ssh -R 0.0.0.0:3000:localhost:3000 -R 0.0.0.0:8000:localhost:8000 user@vps-ip -N
```

---

## 3. Konfiguracja publicznego URL

Po ustawieniu adresu, zaktualizuj `.env`:

```env
# Opcja A — własna domena
PUBLIC_BASE_URL=https://twoja-domena.pl
PUBLIC_API_URL=https://api.twoja-domena.pl

# Opcja B — Cloudflare Tunnel
CLOUDFLARE_TUNNEL_URL=https://xxxx.trycloudflare.com

# Opcja C — ngrok
NGROK_URL=https://xxxx.ngrok.io

# CORS — dodaj swój publiczny adres (oddziel przecinkiem)
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://192.168.0.109:3000,https://twoja-domena.pl
```

Dodaj do `web_portal/.env.local` (Next.js):
```env
# Jeśli backend jest pod innym adresem niż frontend
NEXT_PUBLIC_API_URL=https://api.twoja-domena.pl
BACKEND_URL=https://api.twoja-domena.pl
```

---

## 4. Przykładowa konfiguracja Nginx (reverse proxy)

Plik: `/etc/nginx/sites-available/rldc`

```nginx
# Frontend (Next.js)
server {
    listen 80;
    server_name twoja-domena.pl www.twoja-domena.pl;

    # Przekierowanie HTTP → HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name twoja-domena.pl www.twoja-domena.pl;

    ssl_certificate /etc/letsencrypt/live/twoja-domena.pl/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/twoja-domena.pl/privkey.pem;

    # SSE / streaming logów — wyłącz buforowanie
    proxy_buffering off;
    proxy_cache off;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;   # ważne dla SSE
    }
}

# Backend API (opcjonalnie osobna subdomena)
server {
    listen 443 ssl http2;
    server_name api.twoja-domena.pl;

    ssl_certificate /etc/letsencrypt/live/api.twoja-domena.pl/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.twoja-domena.pl/privkey.pem;

    proxy_buffering off;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }
}
```

SSL z Let's Encrypt:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d twoja-domena.pl -d api.twoja-domena.pl
```

---

## 5. Komenda Telegram `/ip`

Po konfiguracji `.env`, wyślij w Telegramie:
```
/ip
```

Bot odpowie:
```
🖥️ RLdC AiNalyzer — adres panelu

🌐 Publiczny URL: https://twoja-domena.pl
🏠 LAN: http://192.168.0.109:3000
📋 Źródło: PUBLIC_BASE_URL
🔧 Tryb: configured
✅ Status: configured

🕐 2026-04-03 14:20:00
```

---

## 6. Control Center — nowa sekcja debugu

W panelu WWW → menu boczne → **Control Center** (ikona terminala).

Zakładki:
- **Status systemu** — collector, Binance, AI, Telegram, uptime, publiczny URL
- **Szybkie akcje** — 10 przycisków operatorskich (analizuj, skanuj, sprawdź błędy, restart...)
- **Live logi** — SSE stream z bazy, filtry poziomów, eksport
- **AI Chat** — czat z AI (OpenAI lub heurystyczny), dostęp do logów i danych systemu

---

## 7. Bezpieczeństwo publicznego dostępu

### Obowiązkowe przed wystawieniem na zewnątrz:

1. **ADMIN_TOKEN** — ustaw silny token w `.env`:
   ```env
   ADMIN_TOKEN=TwojaBardzoDlugaTajnaFraza123!
   ```
   Sekcja Control Center i akcje operatorskie wymagają tego tokena.

2. **CORS** — ogranicz do swojej domeny:
   ```env
   CORS_ALLOWED_ORIGINS=https://twoja-domena.pl
   ```

3. **SSL/HTTPS** — obowiązkowo dla dostępu z internetu.

4. **Nginx rate limiting** — dodaj do konfiguracji:
   ```nginx
   limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;
   location /api/ {
       limit_req zone=api burst=20 nodelay;
       ...
   }
   ```

5. **Nie** wystawiaj bazy SQLite bezpośrednio.

6. **Nie** ujawniaj `.env` — jest w `.gitignore`.

---

## 8. Uruchomienie

```bash
# Lokalnie
bash scripts/start_dev.sh

# Status
bash scripts/status_dev.sh

# Z publicznym tunelem Cloudflare (w osobnym terminalu)
cloudflared tunnel --url http://localhost:3000

# Po uruchomieniu tunelu — ustaw w .env:
# CLOUDFLARE_TUNNEL_URL=https://xxxx.trycloudflare.com
# Zrestartuj backend:
# bash scripts/stop_dev.sh && bash scripts/start_dev.sh
```

---

## 9. Sprawdzenie publicznego URL (API)

```bash
curl http://localhost:8000/api/system/public-url
```

Odpowiedź:
```json
{
  "success": true,
  "data": {
    "public_url": "https://xxxx.trycloudflare.com",
    "lan_url": "http://192.168.0.109:3000",
    "source": "TUNNEL_URL",
    "mode": "tunnel",
    "status": "tunnel_active"
  }
}
```
