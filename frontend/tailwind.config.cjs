module.exports = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "#0d0f12",
        slate: "#1c222b",
        mist: "#f2f5f7",
        sand: "#f8f5ef",
        teal: "#0f766e",
        amber: "#b45309",
        crimson: "#991b1b"
      },
      fontFamily: {
        display: ["var(--font-display)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"]
      },
      boxShadow: {
        card: "0 18px 60px rgba(13, 15, 18, 0.12)"
      }
    }
  },
  plugins: []
};
