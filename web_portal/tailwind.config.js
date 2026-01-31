/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Dark theme colors from template
        'rldc-dark': {
          bg: '#0a1219',
          card: '#111c26',
          border: '#1e2d3d',
          hover: '#1a2730',
        },
        // Teal/Green accent colors
        'rldc-teal': {
          primary: '#14b8a6',
          light: '#2dd4bf',
          dark: '#0f766e',
        },
        'rldc-green': {
          primary: '#10b981',
          light: '#34d399',
        },
        // Status colors
        'rldc-red': {
          primary: '#ef4444',
          light: '#f87171',
        },
      },
    },
  },
  plugins: [],
}
