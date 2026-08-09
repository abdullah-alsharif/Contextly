import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: "#F8FAFC",
        surfacehigh: "#FFFFFF",
        "ink-900": "#0F172A",
        "ink-700": "#1E293B",
        line: "#E2E8F0",
        divider: "#F1F5F9",
        secondary: "#3B82F6",
        success: "#10B981",
        warning: "#F59E0B",
        error: "#EF4444",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        display: ["Geist", "Inter", "system-ui", "sans-serif"],
      },
      spacing: {
        "stack-sm": "8px",
        "stack-md": "16px",
        "stack-lg": "24px",
        "stack-xl": "48px",
      },
      borderRadius: {
        standard: "0.5rem",
        large: "1rem",
        xl: "1.5rem",
      },
      boxShadow: {
        floating: "0 10px 15px -3px rgba(0,0,0,0.1)",
      },
    },
  },
  plugins: [],
};

export default config;