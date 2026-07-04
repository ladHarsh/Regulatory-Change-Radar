/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      fontWeight: {
        '500': '500',
        '600': '600',
        '700': '700',
        '800': '800',
      },
    },
  },
  plugins: [],
}
