import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"], weight: ["300", "400", "500", "600"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "GovSearch — Agency knowledge, searchable",
  description: "Search, organise and ask questions across agency policies, SOPs, circulars, guidelines, reports and minutes.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
