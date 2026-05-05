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

interface InternalState extends EnrichmentStreamState {
  forSessionId: string | null;
}

const INITIAL_INTERNAL: InternalState = {
  forSessionId: null,
  started: null,
  rows: [],
  logs: [],
  status: "connecting",
  error: null,
};

const DEFAULTS: EnrichmentStreamState = {
  started: null,
  rows: [],
  logs: [],
  status: "connecting",
  error: null,
};

export function useEnrichmentStream(
  sessionId: string | null
): EnrichmentStreamState {
  const [state, setState] = useState<InternalState>(INITIAL_INTERNAL);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!sessionId) return;

    const fresh = (
      patch: (s: InternalState) => Partial<InternalState>
    ): InternalState => {
      const base: InternalState = { ...INITIAL_INTERNAL, forSessionId: sessionId };
      return { ...base, ...patch(base) };
    };

    const update = (patch: (s: InternalState) => Partial<InternalState>) => {
      setState((s) =>
        s.forSessionId === sessionId
          ? { ...s, ...patch(s) }
          : fresh(patch),
      );
    };

    const es = new EventSource(`${API_URL}/api/scrape/${sessionId}/stream`);
    esRef.current = es;

    es.addEventListener("log", (e) => {
      const data: LogEntry = JSON.parse(e.data);
      update((s) => ({ status: "streaming", logs: [...s.logs, data] }));
    });

    es.addEventListener("enrichment_started", (e) => {
      const data: EnrichmentStartedEvent = JSON.parse(e.data);
      update(() => ({ status: "streaming", started: data }));
    });

    es.addEventListener("enrichment_row", (e) => {
      const data: EnrichmentRowEvent = JSON.parse(e.data);
      update((s) => ({ status: "streaming", rows: [...s.rows, data] }));
    });

    es.addEventListener("done", () => {
      update(() => ({ status: "done" }));
      es.close();
    });

    es.addEventListener("cancelled", () => {
      update(() => ({ status: "cancelled" }));
      es.close();
    });

    es.addEventListener("error", (e) => {
      // Server-sent "error" events carry a JSON body; connection drops don't.
      const raw = (e as MessageEvent).data;
      if (typeof raw === "string" && raw) {
        try {
          const data = JSON.parse(raw) as { message?: string };
          update(() => ({
            status: "error",
            error: data.message ?? "Enrichment failed",
          }));
          es.close();
          return;
        } catch {
          // fall through to connection-level handling
        }
      }
      if (es.readyState === EventSource.CLOSED) {
        update(() => ({ status: "error", error: "Connection lost" }));
      }
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [sessionId]);

  if (state.forSessionId !== sessionId) {
    return DEFAULTS;
  }
  const { forSessionId: _ignored, ...exposed } = state;
  void _ignored;
  return exposed;
}
