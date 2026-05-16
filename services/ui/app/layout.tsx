import type { Metadata } from "next";
import "./globals.css";
import NavSidebar from "@/components/nav-sidebar";
import { getSources } from "@/lib/api";

export const metadata: Metadata = {
  title: "SentinelAI",
  description: "AI agent observability and debugging",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  let lastSyncedAt: string | null = null;
  try {
    const sources = await getSources();
    const timestamps = sources.items
      .map((s) => s.last_synced_at)
      .filter(Boolean) as string[];
    if (timestamps.length > 0) {
      lastSyncedAt = timestamps.reduce((a, b) => (a > b ? a : b));
    }
  } catch {
    // sidebar still renders — sync status just hidden
  }

  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden bg-slate-50">
        <NavSidebar lastSyncedAt={lastSyncedAt} />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </body>
    </html>
  );
}
