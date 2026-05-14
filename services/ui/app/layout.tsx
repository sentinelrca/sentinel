import type { Metadata } from "next";
import "./globals.css";
import NavSidebar from "@/components/nav-sidebar";

export const metadata: Metadata = {
  title: "SentinelAI",
  description: "AI agent observability and debugging",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden bg-slate-50">
        <NavSidebar />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </body>
    </html>
  );
}
