import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/**
 * Qosmic NOC design tokens — derived from the existing qosmic_mockup so the
 * stakeholder demo feels continuous. Both light and dark modes are first-class.
 */
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1440px" },
    },
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-jet)", "ui-monospace", "Menlo", "monospace"],
      },
      colors: {
        // semantic — drive everything via CSS vars in globals.css for theme-swap
        bg: {
          0: "hsl(var(--bg-0) / <alpha-value>)",
          1: "hsl(var(--bg-1) / <alpha-value>)",
          2: "hsl(var(--bg-2) / <alpha-value>)",
          3: "hsl(var(--bg-3) / <alpha-value>)",
          elev: "hsl(var(--bg-elev) / <alpha-value>)",
        },
        line: {
          subtle: "hsl(var(--line-subtle) / <alpha-value>)",
          DEFAULT: "hsl(var(--line) / <alpha-value>)",
          strong: "hsl(var(--line-strong) / <alpha-value>)",
        },
        ink: {
          0: "hsl(var(--ink-0) / <alpha-value>)",
          1: "hsl(var(--ink-1) / <alpha-value>)",
          2: "hsl(var(--ink-2) / <alpha-value>)",
          3: "hsl(var(--ink-3) / <alpha-value>)",
        },
        cy: {
          DEFAULT: "hsl(var(--cy) / <alpha-value>)",
          soft: "hsl(var(--cy-soft) / <alpha-value>)",
        },
        teal: { DEFAULT: "hsl(var(--teal) / <alpha-value>)" },
        vio: {
          DEFAULT: "hsl(var(--vio) / <alpha-value>)",
          soft: "hsl(var(--vio-soft) / <alpha-value>)",
        },
        ok: {
          DEFAULT: "hsl(var(--ok) / <alpha-value>)",
          soft: "hsl(var(--ok-soft) / <alpha-value>)",
        },
        warn: {
          DEFAULT: "hsl(var(--warn) / <alpha-value>)",
          soft: "hsl(var(--warn-soft) / <alpha-value>)",
        },
        bad: {
          DEFAULT: "hsl(var(--bad) / <alpha-value>)",
          soft: "hsl(var(--bad-soft) / <alpha-value>)",
        },
        info: {
          DEFAULT: "hsl(var(--info) / <alpha-value>)",
          soft: "hsl(var(--info-soft) / <alpha-value>)",
        },
      },
      boxShadow: {
        glow: "0 0 0 1px hsl(var(--cy) / 0.25), 0 18px 60px -24px hsl(var(--cy) / 0.45)",
        card: "0 1px 0 hsl(var(--ink-0) / 0.04), 0 24px 48px -32px rgba(0,0,0,.6)",
      },
      backgroundImage: {
        "grad-cosmic":
          "radial-gradient(1200px 600px at 75% -10%, hsl(var(--vio) / 0.18), transparent 60%), radial-gradient(900px 500px at 10% 110%, hsl(var(--cy) / 0.16), transparent 60%), linear-gradient(180deg, hsl(var(--bg-0)) 0%, hsl(var(--bg-1)) 100%)",
        "grid-bg":
          "linear-gradient(hsl(var(--line) / 0.18) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--line) / 0.18) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "32px 32px",
      },
      keyframes: {
        scanmove: {
          "0%": { transform: "translateY(110%)" },
          "50%": { transform: "translateY(-10%)" },
          "100%": { transform: "translateY(110%)" },
        },
        pulse: {
          "0%": { boxShadow: "0 0 0 0 currentColor", opacity: "0.55" },
          "70%": { boxShadow: "0 0 0 10px transparent", opacity: "0" },
          "100%": { boxShadow: "0 0 0 0 transparent", opacity: "0" },
        },
        ticker: {
          from: { transform: "translateX(0)" },
          to: { transform: "translateX(-50%)" },
        },
      },
      animation: {
        scanmove: "scanmove 2.6s ease-in-out infinite",
        pulse: "pulse 1.6s infinite",
        ticker: "ticker 40s linear infinite",
      },
    },
  },
  plugins: [animate],
};

export default config;
