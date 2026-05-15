"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Database, GitBranch, ShieldAlert } from "lucide-react";
import { clsx } from "clsx";

const NAV = [
  { href: "/traces",   label: "Traces",   icon: GitBranch },
  { href: "/insights", label: "Insights", icon: ShieldAlert },
  { href: "/sources",  label: "Sources",  icon: Database },
];

export default function NavSidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-56 flex-col bg-slate-900 text-slate-400">
      {/* Logo */}
      <div className="flex items-center gap-2 px-4 py-5 text-white">
        <Activity size={20} className="text-indigo-400" />
        <span className="text-sm font-semibold tracking-wide">SentinelAI</span>
      </div>

      <nav className="flex-1 space-y-0.5 px-2 py-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-slate-700 text-white"
                  : "hover:bg-slate-800 hover:text-slate-200"
              )}
            >
              <Icon size={16} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-3 text-xs text-slate-600">v0.1.0</div>
    </aside>
  );
}
