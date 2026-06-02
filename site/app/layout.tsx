import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "USAspending Explorer (prototype)",
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
        <div className="bg-amber-100 text-amber-900 border-b border-amber-300 text-center text-sm px-4 py-2">
          <span className="font-semibold">⚠️ Prototype — do not use for analysis.</span>{" "}
          Work in progress; data and figures are not yet verified and may be incomplete or wrong.
        </div>
        <header className="border-b bg-background/80 backdrop-blur sticky top-0 z-10">
          <div className="mx-auto flex max-w-7xl items-center gap-8 px-6 py-3">
            <Link href="/" className="font-semibold tracking-tight">USAspending</Link>
            <nav className="flex gap-5">
              <NavLink href="/">Spending Explorer</NavLink>
              <NavLink href="/table-builder">Table Builder</NavLink>
              <NavLink href="/downloads">Data Downloads</NavLink>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
        <footer className="border-t mt-12">
          <div className="mx-auto max-w-7xl px-6 py-6 flex flex-wrap gap-x-2 gap-y-1 text-sm text-muted-foreground">
            <span>
              Source:{" "}
              <a className="underline hover:text-foreground" href="https://files.usaspending.gov/award_data_archive/" target="_blank" rel="noreferrer">USAspending Award Data Archive</a>{" "}
              (public domain), FY2007–2026.
            </span>
            <span>
              Parquet mirror on{" "}
              <a className="underline hover:text-foreground" href="https://huggingface.co/datasets/abigailhaddad/usaspending-bulk-awards" target="_blank" rel="noreferrer">Hugging Face</a>.
            </span>
            <span className="font-medium text-amber-700">Prototype — not for analysis.</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
