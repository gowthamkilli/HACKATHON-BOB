/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        chrome: "#151515",
        panel: "#1b1b1b",
        border: "#2a2a2a",
        accent: "#0f62fe",
        pass: "#24a148",
        fail: "#da1e28",
        inconclusive: "#f1c21b",
        invalid: "#6f6f6f",
      },
      fontFamily: {
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
