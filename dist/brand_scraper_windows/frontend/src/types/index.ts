export type Platform = "official_site" | "shopee";

export interface CategoryResult {
  category: string;
  status: "found" | "not_found";
  lowest_price: number | null;
  highest_price: number | null;
  products_scanned: number;
}

export interface ShopeeProductRecord {
  // Kept in sync with backend/app/platforms/shopee/models.py::ShopeeProductRecord.
  // See docs/plans/2026-04-10-shopee-spike-notes.md for why the original design
  // doc's richer schema (stock, category_path, brand, shop_id) was dropped —
  // those fields aren't in the shop-grid DOM and the XHR path is blocked.
  item_id: number;
  product_name: string;
  product_url: string;
  image_url: string | null;
  price: number | null;
  mrp: number | null;
  currency: string;
  discount_pct: number | null;
  rating_star: number | null;
  historical_sold_count: number | null;
  is_sold_out: boolean;
  scraped_at: string;
}

export interface ScrapeStartResponse {
  scrape_id: string;
}

export interface DoneInfo {
  brand: string;
  count: number;
  file: string;
}

export interface LogEntry {
  message: string;
  level: "info" | "success" | "warning" | "error";
}

export interface Brand {
  id: string;
  name: string;
  created_at: string;
}

export interface RunAggregates {
  product_count: number;
  price_min: number | null;
  price_max: number | null;
  category_count: number | null;
}

export interface RunSummary {
  id: string;
  status: "ok" | "error" | "cancelled" | "in_progress" | string;
  aggregates: RunAggregates;
  created_at: string;
}

export interface BrandSummary {
  id: string;
  name: string;
  created_at: string;
  source_count: number;
  latest_run: RunSummary | null;
  latest_source_platform: string | null;
  latest_source_id: string | null;
}

export interface Source {
  id: string;
  brand_id: string;
  platform: Platform;
  spec: Record<string, unknown>;
  created_at: string;
}

export interface BrandDetail {
  id: string;
  name: string;
  created_at: string;
  sources: Source[];
  latest_run_by_source: Record<string, RunSummary | null>;
}
