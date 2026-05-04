"use client";

import { useCallback, useState } from "react";

const STORAGE_KEY = "brand-scraper:dismissed-categories";

type SectionMap = Partial<Record<string, string[]>>;
type Store = Record<string, SectionMap>;

function readStore(): Store {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? (parsed as Store) : {};
  } catch {
    return {};
  }
}

function writeStore(store: Store) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // quota or disabled storage — ignore
  }
}

export interface UseDismissedCategoriesResult {
  get: (section: string) => string[];
  dismiss: (section: string, category: string) => void;
  undismiss: (section: string, category: string) => void;
}

export function useDismissedCategories(
  brandId: string | null | undefined,
): UseDismissedCategoriesResult {
  const [store, setStore] = useState<Store>(() => readStore());

  const get = useCallback(
    (section: string): string[] => {
      if (!brandId) return [];
      return store[brandId]?.[section] ?? [];
    },
    [brandId, store],
  );

  const dismiss = useCallback(
    (section: string, category: string) => {
      if (!brandId) return;
      const normalized = category.trim().toLowerCase();
      if (!normalized) return;
      setStore((prev) => {
        const brandMap = prev[brandId] ?? {};
        const existing = brandMap[section] ?? [];
        if (existing.includes(normalized)) return prev;
        const next: Store = {
          ...prev,
          [brandId]: {
            ...brandMap,
            [section]: [...existing, normalized],
          },
        };
        writeStore(next);
        return next;
      });
    },
    [brandId],
  );

  const undismiss = useCallback(
    (section: string, category: string) => {
      if (!brandId) return;
      const normalized = category.trim().toLowerCase();
      if (!normalized) return;
      setStore((prev) => {
        const brandMap = prev[brandId];
        if (!brandMap) return prev;
        const existing = brandMap[section];
        if (!existing || !existing.includes(normalized)) return prev;
        const nextList = existing.filter((c) => c !== normalized);
        const next: Store = {
          ...prev,
          [brandId]: {
            ...brandMap,
            [section]: nextList,
          },
        };
        writeStore(next);
        return next;
      });
    },
    [brandId],
  );

  return { get, dismiss, undismiss };
}
