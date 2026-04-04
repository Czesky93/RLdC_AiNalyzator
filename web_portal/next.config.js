/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Zezwól na połączenia z zewnętrznych adresów (np. 192.168.0.109, publiczne IP, Cloudflare tunnel)
  allowedDevOrigins: [
    '192.168.0.109',
    '0.0.0.0',
    '*.trycloudflare.com',
    'reducing-yrs-yes-harmony.trycloudflare.com',
  ],
  async rewrites() {
    // W produkcji API_URL może wskazywać na inny host (np. https://api.twoja-domena.pl)
    const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000'
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: '/health',
        destination: `${backendUrl}/health`,
      },
    ]
  },
  // Zmienne środowiskowe dostępne w przeglądarce (NEXT_PUBLIC_*)
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || '',
  },
}

module.exports = nextConfig
