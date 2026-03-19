export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

async function parseResponse(r: Response) {
  if (!r.ok) {
    const message = await r.text();
    throw new Error(message || `Request failed with status ${r.status}`);
  }
  return r.json();
}

export async function apiAsk(query: string, k: number = 4) {
  const r = await fetch(`${API_BASE}/api/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, k })
  });
  return parseResponse(r);
}

export async function apiIngest() {
  const r = await fetch(`${API_BASE}/api/ingest`, { method: 'POST' });
  return parseResponse(r);
}

export async function apiMetrics() {
  const r = await fetch(`${API_BASE}/api/metrics`);
  return parseResponse(r);
}
