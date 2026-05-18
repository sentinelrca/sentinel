import type { Metadata } from "next";
import "./globals.css";
import NavSidebar from "@/components/nav-sidebar";
import { getSources, listProjects } from "@/lib/api";

export const metadata: Metadata = {
  title: "SentinelAI",
  description: "AI agent observability and debugging",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  let lastSyncedAt: string | null = null;
  let projects: Array<{ id: string; name: string; status: string }> = [];

  const [sourcesResult, projectsResult] = await Promise.allSettled([
    getSources(),
    listProjects(),
  ]);

  if (sourcesResult.status === "fulfilled") {
    const timestamps = sourcesResult.value.items
      .map((s) => s.last_synced_at)
      .filter(Boolean) as string[];
    if (timestamps.length > 0) {
      lastSyncedAt = timestamps.reduce((a, b) => (a > b ? a : b));
    }
  }

  if (projectsResult.status === "fulfilled") {
    projects = projectsResult.value.items.map((p) => ({
      id: p.id,
      name: p.name,
      status: p.status,
    }));
  }

  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden bg-slate-50">
        <NavSidebar lastSyncedAt={lastSyncedAt} projects={projects} />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </body>
    </html>
  );
}
