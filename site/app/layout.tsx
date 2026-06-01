import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "USAspending Explorer",
  description: "Aggregate, visualize, and download federal contract & assistance spending.",
};

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground">
      {children}
    </Link>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <header className="border-b bg-background/80 backdrop-blur sticky top-0 z-10">
          <div className="mx-auto flex max-w-7xl items-center gap-8 px-6 py-3">
            <Link href="/" className="font-semibold tracking-tight">USAspending</Link>
            <nav className="flex gap-5">
              <NavLink href="/">Table Builder</NavLink>
              <NavLink href="/visualizations">Visualizations</NavLink>
              <NavLink href="/downloads">Data Downloads</NavLink>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
