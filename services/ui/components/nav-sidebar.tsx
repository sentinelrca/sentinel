"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Database, FolderOpen, GitBranch, Settings, ShieldAlert } from "lucide-react";
import { clsx } from "clsx";

const LIVE_NAV = [
  { href: "/traces",   label: "Traces",   icon: GitBranch },
  { href: "/insights", label: "Insights", icon: ShieldAlert },
  { href: "/sources",  label: "Sources",  icon: Database },
];

const STATUS_DOT: Record<string, string> = {
  ready:     "bg-green-400",
  importing: "bg-blue-400 animate-pulse",
  analyzing: "bg-indigo-400 animate-pulse",
  error:     "bg-red-400",
  pending:   "bg-slate-400",
};

function SyncDot({ lastSyncedAt }: { lastSyncedAt: string | null }) {
  if (!lastSyncedAt) return null;

  const diffMin = Math.round((Date.now() - new Date(lastSyncedAt).getTime()) / 60_000);
  const dotColor =
    diffMin <= 30 ? "bg-green-400" :
    diffMin <= 120 ? "bg-amber-400" :
    "bg-red-400";
  const label =
    diffMin < 60 ? `synced ${diffMin}m ago` : `synced ${Math.round(diffMin / 60)}h ago`;

  return (
    <div className="flex items-center gap-1.5 px-4 py-3 text-xs text-slate-500">
      <span className={clsx("h-2 w-2 shrink-0 rounded-full", dotColor)} />
      {label}
    </div>
  );
}

interface ProjectEntry {
  id: string;
  name: string;
  status: string;
}

interface Props {
  lastSyncedAt?: string | null;
  projects?: ProjectEntry[];
}

export default function NavSidebar({ lastSyncedAt, projects = [] }: Props) {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-56 flex-col bg-slate-900 text-slate-400">
      {/* Logo */}
      <div className="flex items-center gap-2 px-4 py-5 text-white">
        <Activity size={20} className="text-indigo-400" />
        <span className="text-sm font-semibold tracking-wide">SentinelAI</span>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {/* Live section */}
        <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600">
          Live
        </p>
        <div className="mb-3 space-y-0.5">
          {LIVE_NAV.map(({ href, label, icon: Icon }) => {
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
        </div>

        {/* Projects section */}
        <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600">
          Projects
        </p>
        <div className="mb-3 space-y-0.5">
          <Link
            href="/projects"
            className={clsx(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
              pathname === "/projects"
                ? "bg-slate-700 text-white"
                : "hover:bg-slate-800 hover:text-slate-200"
            )}
          >
            <FolderOpen size={16} />
            All Projects
          </Link>
          {projects.map((p) => {
            const active = pathname.startsWith(`/projects/${p.id}`);
            const dotClass = STATUS_DOT[p.status] ?? STATUS_DOT.pending;
            return (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className={clsx(
                  "flex items-center gap-2 rounded-md px-3 py-1.5 text-xs transition-colors",
                  active
                    ? "bg-slate-700 text-white"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                )}
              >
                <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", dotClass)} />
                <span className="truncate">{p.name}</span>
              </Link>
            );
          })}
        </div>

        {/* Settings */}
        <div className="space-y-0.5">
          {[{ href: "/settings/rules", label: "Settings", icon: Settings }].map(
            ({ href, label, icon: Icon }) => {
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
            }
          )}
        </div>
      </nav>

      <SyncDot lastSyncedAt={lastSyncedAt ?? null} />
      <div className="px-4 pb-3 text-xs text-slate-600">v0.1.0</div>
    </aside>
  );
}
