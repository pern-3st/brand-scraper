"use client";

import { useEffect, useRef } from "react";
import { LogEntry } from "@/types";

interface LogFeedProps {
  logs: LogEntry[];
  streaming: boolean;
}

const LEVEL_COLORS: Record<string, string> = {
  info: "text-foreground/70",
  success: "text-emerald-600",
  warning: "text-amber-600",
  error: "text-pink-600",
};

const LEVEL_BORDER: Record<string, string> = {
  info: "border-l-purple-200",
  success: "border-l-emerald-300",
  warning: "border-l-amber-300",
  error: "border-l-pink-300",
};

export default function LogFeed({ logs, streaming }: LogFeedProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !stickToBottom.current) return;
    el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    // "Stuck" if within 40px of bottom
    stickToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  function scrollToBottom() {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    stickToBottom.current = true;
  }

  return (
    <div className="relative rounded-2xl overflow-hidden ring-1 ring-border shadow-md shadow-accent/5 bg-card">
      {/* Header */}
      <div className="px-4 py-2.5 flex items-center gap-2 border-b border-border">
        {streaming && (
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-accent" />
          </span>
        )}
        {!streaming && (
          <span className="h-2.5 w-2.5 rounded-full bg-muted-fg/40" />
        )}
        <span className="text-xs text-muted-fg font-medium">
          {streaming ? "Live Logs" : "Logs"}
        </span>
      </div>

      {/* Log content */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="px-4 py-3 max-h-96 overflow-y-auto font-mono text-xs leading-relaxed scroll-smooth bg-accent-soft/30"
      >
        {logs.length === 0 && (
          <p className="text-muted-fg italic">Waiting for agent...</p>
        )}

        {logs.map((log, i) => (
          <div
            key={i}
            className={`log-line border-l-2 pl-3 py-0.5 ${LEVEL_COLORS[log.level] ?? "text-foreground/70"} ${LEVEL_BORDER[log.level] ?? "border-l-purple-200"}`}
          >
            {log.message}
          </div>
        ))}

        {streaming && (
          <span className="cursor-blink inline-block w-2 h-4 bg-accent ml-3 mt-1 rounded-sm" />
        )}
      </div>

      {/* Scroll-to-bottom FAB */}
      {logs.length > 20 && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-3 right-3 bg-accent/10 hover:bg-accent/20 text-accent rounded-full p-1.5 text-xs shadow-sm transition-colors"
          aria-label="Scroll to bottom"
        >
          ↓
        </button>
      )}
    </div>
  );
}
