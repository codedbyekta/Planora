/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#161A2E",        // near-black indigo, primary text
        surface: "#F6F7FB",    // app background, cool off-white
        card: "#FFFFFF",
        primary: {
          DEFAULT: "#4F46E5",  // indigo - buttons, links, nav highlight
          dark: "#4338CA",
          light: "#EEF2FF",
        },
        focus: {
          DEFAULT: "#F59E0B",  // amber - Pomodoro timer / "focus mode"
          light: "#FEF3C7",
        },
        success: {
          DEFAULT: "#10B981",
          light: "#D1FAE5",
        },
        danger: {
          DEFAULT: "#EF4444",
          light: "#FEE2E2",
        },
        border: "#E4E6F0",
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        sans: ["'Inter'", "sans-serif"],
      },
    },
  },
  plugins: [],
}
