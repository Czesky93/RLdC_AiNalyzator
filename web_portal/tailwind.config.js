/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Space Grotesk', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'Liberation Mono', 'monospace'],
      },
      colors: {
        // Dark theme colors from template
        'rldc-dark': {
          bg: '#0a1219',
          darker: '#060b10',
          card: '#111c26',
          border: '#1e2d3d',
          hover: '#1a2730',
        },
        // Teal/Cyan accent colors
        'rldc-teal': {
          primary: '#14b8a6',
          light: '#2dd4bf',
          dark: '#0f766e',
        },
        'rldc-green': {
          primary: '#10b981',
          light: '#34d399',
          dark: '#059669',
        },
        // Status colors
        'rldc-red': {
          primary: '#ef4444',
          light: '#f87171',
          dark: '#dc2626',
        },
        'rldc-orange': {
          primary: '#f59e0b',
          light: '#fbbf24',
          dark: '#d97706',
        },
        // Additional colors
        'teal-primary': '#14b8a6',
        'green-primary': '#10b981',
        'red-primary': '#ef4444',
        'orange-primary': '#f59e0b',
      },
      boxShadow: {
        'glow-teal': '0 0 20px rgba(20, 184, 166, 0.3)',
        'glow-green': '0 0 20px rgba(16, 185, 129, 0.3)',
        'glow-red': '0 0 20px rgba(239, 68, 68, 0.3)',
        'elevation': '0 18px 40px rgba(0, 0, 0, 0.45)',
      },
    },
  },
  plugins: [],
}
