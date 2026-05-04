"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL } from "@/lib/api";
import type {
  EnrichmentRowEvent,
  EnrichmentStartedEvent,
  LogEntry,
} from "@/types";

export type EnrichmentStatus =
  | "connecting"
  | "streaming"
  | "done"
  | "error"
  | "cancelled";

export interface EnrichmentStreamState {
  started: EnrichmentStartedEvent | null;
  rows: EnrichmentRowEvent[];
  logs: LogEntry[];
  status: EnrichmentStatus;
  error: string | null;
}

export function useEnrichmentStream(
  sessionId: string | null
): EnrichmentStreamState {
  const [started, setStarted] = useState<EnrichmentStartedEvent | null>(null);
  const [rows, setRows] = useState<EnrichmentRowEvent[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<EnrichmentStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!sessionId) return;

    setStarted(null);
    setRows([]);
    setLogs([]);
    setStatus("connecting");
    setError(null);

    const es = new EventSource(`${API_URL}/api/scrape/${sessionId}/stream`);
    esRef.current = es;

    es.addEventListener("log", (e) => {
      setStatus("streaming");
      const data: LogEntry = JSON.parse(e.data);
      setLogs((prev) => [...prev, data]);
    });

    es.addEventListener("enrichment_started", (e) => {
      setStatus("streaming");
      const data: EnrichmentStartedEvent = JSON.parse(e.data);
      setStarted(data);
    });

    es.addEventListener("enrichment_row", (e) => {
      setStatus("streaming");
      const data: EnrichmentRowEvent = JSON.parse(e.data);
      setRows((prev) => [...prev, data]);
    });

    es.addEventListener("done", () => {
      setStatus("done");
      es.close();
    });

    es.addEventListener("cancelled", () => {
      setStatus("cancelled");
      es.close();
    });

    es.addEventListener("error", (e) => {
      // Server-sent "error" events carry a JSON body; connection drops don't.
      const raw = (e as MessageEvent).data;
      if (typeof raw === "string" && raw) {
        try {
          const data = JSON.parse(raw) as { message?: string };
          setError(data.message ?? "Enrichment failed");
          setStatus("error");
          es.close();
          return;
        } catch {
          // fall through to connection-level handling
        }
      }
      if (es.readyState === EventSource.CLOSED) {
        setError("Connection lost");
        setStatus("error");
      }
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [sessionId]);

  return { started, rows, logs, status, error };
}
