"use client";

import { useState, useEffect, useRef } from "react";
import { API_URL } from "@/lib/api";
import { LogEntry, ProductRecord, ProductUpdate, DoneInfo } from "@/types";

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

interface InternalState extends ScrapeStreamState {
  forScrapeId: string | null;
}

const INITIAL_INTERNAL: InternalState = {
  forScrapeId: null,
  logs: [],
  products: [],
  doneInfo: null,
  status: "connecting",
  error: null,
  pausedReason: null,
};

const DEFAULTS: ScrapeStreamState = {
  logs: [],
  products: [],
  doneInfo: null,
  status: "connecting",
  error: null,
  pausedReason: null,
};

export function useScrapeStream(scrapeId: string | null): ScrapeStreamState {
  const [state, setState] = useState<InternalState>(INITIAL_INTERNAL);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!scrapeId) return;

    const fresh = (
      patch: (s: InternalState) => Partial<InternalState>
    ): InternalState => {
      const base: InternalState = { ...INITIAL_INTERNAL, forScrapeId: scrapeId };
      return { ...base, ...patch(base) };
    };

    const update = (patch: (s: InternalState) => Partial<InternalState>) => {
      setState((s) =>
        s.forScrapeId === scrapeId
          ? { ...s, ...patch(s) }
          : fresh(patch),
      );
    };

    const es = new EventSource(`${API_URL}/api/scrape/${scrapeId}/stream`);
    esRef.current = es;

    es.addEventListener("log", (e) => {
      const data: LogEntry = JSON.parse(e.data);
      update((s) => ({ status: "streaming", logs: [...s.logs, data] }));
    });

    es.addEventListener("product", (e) => {
      const data: ProductRecord = JSON.parse(e.data);
      update((s) => ({
        status: "streaming",
        pausedReason: null,
        products: [...s.products, data],
      }));
    });

    es.addEventListener("product_update", (e) => {
      const upd: ProductUpdate = JSON.parse(e.data);
      update((s) => ({
        products: s.products.map((p) =>
          p.item_id === upd.item_id
            ? {
                ...p,
                monthly_sold_count:
                  upd.monthly_sold_count ?? p.monthly_sold_count,
                monthly_sold_text:
                  upd.monthly_sold_text ?? p.monthly_sold_text,
              }
            : p,
        ),
      }));
    });

    es.addEventListener("login_required", () => {
      update(() => ({ pausedReason: "login" }));
    });

    es.addEventListener("captcha_required", () => {
      update(() => ({ pausedReason: "captcha" }));
    });

    es.addEventListener("done", (e) => {
      const data: DoneInfo = JSON.parse(e.data);
      update(() => ({
        status: "done",
        doneInfo: data,
        pausedReason: null,
      }));
      es.close();
    });

    es.addEventListener("cancelled", (e) => {
      const data: DoneInfo = JSON.parse(e.data);
      update(() => ({
        status: "cancelled",
        doneInfo: data,
        pausedReason: null,
      }));
      es.close();
    });

    es.addEventListener("error", () => {
      if (es.readyState === EventSource.CLOSED) {
        update(() => ({ status: "error", error: "Connection lost" }));
      }
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [scrapeId]);

  if (state.forScrapeId !== scrapeId) {
    return DEFAULTS;
  }
  const { forScrapeId: _ignored, ...exposed } = state;
  void _ignored;
  return exposed;
}
