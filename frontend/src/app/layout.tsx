import type { Metadata, Viewport } from "next";
import { Poppins } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const poppins = Poppins({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: {
    default: "MPSTT CRM",
    template: "%s · MPSTT CRM",
  },
  description:
    "Medical Prism Supplies for Treatment and Technology — prospect-to-payment CRM",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Lets the layout paint under the notch and home indicator so the safe-area
  // insets below are non-zero and actually usable.
  viewportFit: "cover",
  // The on-screen keyboard resizes the viewport instead of floating over it,
  // so a focused field and its error message stay visible.
  interactiveWidget: "resizes-content",
  // Deliberately not locking zoom: pinch-to-zoom is an accessibility feature.
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${poppins.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        {children}
        <Toaster richColors position="top-right" />
      </body>
    </html>
  );
}
