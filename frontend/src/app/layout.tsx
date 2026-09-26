import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quant Copilot",
  description: "An AI research copilot for a simulated market of synthetic indices: measure volatility, detect regimes and backtest strategies honestly.",
};

// Applies a saved theme choice before first paint so there's no flash of the wrong theme.
const themeScript = `try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="h-full">{children}</body>
    </html>
  );
}
