"use client";

import { useState, useEffect, useRef } from "react";
import { API_URL } from "@/lib/api";
import { LogEntry, ProductRecord, DoneInfo } from "@/types";

export type StreamStatus =
  | "connecting"
  | "streaming"
  | "done"
  | "error"
  | "cancelled";

export type PausedReason = "login" | "captcha" | null;

export interface ScrapeStreamState {
  logs: LogEntry[];
  products: ProductRecord[];
  doneInfo: DoneInfo | null;
  status: StreamStatus;
  error: string | null;
  pausedReason: PausedReason;
}

export function useScrapeStream(scrapeId: string | null): ScrapeStreamState {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [products, setProducts] = useState<ProductRecord[]>([]);
  const [doneInfo, setDoneInfo] = useState<DoneInfo | null>(null);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [pausedReason, setPausedReason] = useState<PausedReason>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!scrapeId) return;

    setLogs([]);
    setProducts([]);
    setDoneInfo(null);
    setStatus("connecting");
    setError(null);
    setPausedReason(null);

    const es = new EventSource(`${API_URL}/api/scrape/${scrapeId}/stream`);
    esRef.current = es;

    es.addEventListener("log", (e) => {
      setStatus("streaming");
      const data: LogEntry = JSON.parse(e.data);
      setLogs((prev) => [...prev, data]);
    });

    es.addEventListener("product", (e) => {
      setStatus("streaming");
      setPausedReason(null);
      const data: ProductRecord = JSON.parse(e.data);
      setProducts((prev) => [...prev, data]);
    });

    es.addEventListener("login_required", () => {
      setPausedReason("login");
    });

    es.addEventListener("captcha_required", () => {
      setPausedReason("captcha");
    });

    es.addEventListener("done", (e) => {
      const data: DoneInfo = JSON.parse(e.data);
      setDoneInfo(data);
      setStatus("done");
      setPausedReason(null);
      es.close();
    });

    es.addEventListener("cancelled", (e) => {
      const data: DoneInfo = JSON.parse(e.data);
      setDoneInfo(data);
      setStatus("cancelled");
      setPausedReason(null);
      es.close();
    });

    es.addEventListener("error", () => {
      if (es.readyState === EventSource.CLOSED) {
        setStatus("error");
        setError("Connection lost");
      }
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [scrapeId]);

  return {
    logs,
    products,
    doneInfo,
    status,
    error,
    pausedReason,
  };
}
