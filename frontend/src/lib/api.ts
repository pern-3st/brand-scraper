import {
  Brand,
  BrandDetail,
  BrandSummary,
  Platform,
  RunSummary,
  ScrapeStartResponse,
  Settings,
  Source,
} from "@/types";

// 127.0.0.1 (not "localhost") because uvicorn binds IPv4-only by default and
// modern browsers resolve "localhost" to IPv6 ::1 first — that path would
// connection-refuse and surface as "Failed to fetch".
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export { API_URL };

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export async function listBrands(): Promise<BrandSummary[]> {
  return json(await fetch(`${API_URL}/api/brands`));
}

export async function createBrand(name: string): Promise<Brand> {
  return json(
    await fetch(`${API_URL}/api/brands`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    })
  );
}

export async function deleteBrand(brandId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/brands/${brandId}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
}

export async function getBrand(brandId: string): Promise<BrandDetail> {
  return json(await fetch(`${API_URL}/api/brands/${brandId}`));
}

export async function createSource(
  brandId: string,
  platform: Platform,
  spec: Record<string, unknown>
): Promise<Source> {
  return json(
    await fetch(`${API_URL}/api/brands/${brandId}/sources`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, spec }),
    })
  );
}

export async function updateSource(
  brandId: string,
  sourceId: string,
  spec: Record<string, unknown>
): Promise<Source> {
  return json(
    await fetch(`${API_URL}/api/brands/${brandId}/sources/${sourceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec }),
    })
  );
}

export async function listRuns(
  brandId: string,
  sourceId: string
): Promise<RunSummary[]> {
  return json(
    await fetch(`${API_URL}/api/brands/${brandId}/sources/${sourceId}/runs`)
  );
}

export async function getRun(
  brandId: string,
  sourceId: string,
  runId: string
): Promise<unknown> {
  return json(
    await fetch(
      `${API_URL}/api/brands/${brandId}/sources/${sourceId}/runs/${runId}`
    )
  );
}

export async function deleteRun(
  brandId: string,
  sourceId: string,
  runId: string
): Promise<void> {
  const res = await fetch(
    `${API_URL}/api/brands/${brandId}/sources/${sourceId}/runs/${runId}`,
    { method: "DELETE" }
  );
  if (!res.ok && res.status !== 204) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
}

export async function startScrape(
  brandId: string,
  sourceId: string
): Promise<ScrapeStartResponse> {
  return json(
    await fetch(`${API_URL}/api/scrape/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brand_id: brandId, source_id: sourceId }),
    })
  );
}

export async function cancelScrape(scrapeId: string): Promise<void> {
  await fetch(`${API_URL}/api/scrape/${scrapeId}/cancel`, { method: "POST" });
}

export async function resumeLogin(
  scrapeId: string
): Promise<{ status: string }> {
  const res = await fetch(
    `${API_URL}/api/scrape/${scrapeId}/login_complete`,
    { method: "POST" }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to resume login (${res.status}): ${text}`);
  }
  return res.json();
}

export async function getSettings(): Promise<Settings> {
  return json(await fetch(`${API_URL}/api/settings`));
}

export async function updateSettings(
  patch: { openrouter_api_key?: string; openrouter_model?: string }
): Promise<Settings> {
  return json(
    await fetch(`${API_URL}/api/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}
