export type Platform = "official_site" | "shopee";

export interface ProductRecord {
  // Mirrors backend/app/models.py::ProductRecord.
  // Core (populated by every scraper)
  product_name: string;
  product_url: string | null;
  image_url: string | null;
  price: number | null;
  mrp: number | null;
  currency: string;
  discount_pct: number | null;
  is_sold_out: boolean;
  scraped_at: string;

  // Shopee-only (null on official_site)
  item_id: number | null;
  rating_star: number | null;
  historical_sold_count: number | null;

  // Official-site-only (null on shopee)
  category: string | null;
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

export interface Settings {
  openrouter_api_key_set: boolean;
  openrouter_api_key_hint: string;
  openrouter_model: string;
}
