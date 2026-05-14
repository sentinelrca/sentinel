import { clsx } from "clsx";
import type { Severity } from "@/lib/types";

const COLORS: Record<Severity, string> = {
  CRITICAL: "bg-red-100 text-red-700 border-red-200",
  HIGH: "bg-orange-100 text-orange-700 border-orange-200",
  WARNING: "bg-yellow-100 text-yellow-700 border-yellow-200",
  INFO: "bg-blue-100 text-blue-700 border-blue-200",
};

interface Props {
  severity: Severity;
  size?: "sm" | "lg";
}

export default function SeverityBadge({ severity, size = "sm" }: Props) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded border font-medium",
        size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
        COLORS[severity] ?? "bg-slate-100 text-slate-600 border-slate-200"
      )}
    >
      {severity}
    </span>
  );
}
