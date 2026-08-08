/** API helper — wraps fetch with JWT auth token from localStorage. */

function getToken(): string | null {
  return localStorage.getItem("cagentos_jwt") || null;
}

export async function api<T = any>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(path, { ...options, headers });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json();
}

export interface Opinion {
  id: string;
  conversation_id: string;
  message_id: string;
  selected_text: string;
  category: string;
  note: string;
  tags: string[];
  created_at: string;
}

export const opinionsApi = {
  list: (category?: string) =>
    api<{ items: Opinion[]; total: number }>(
      "/api/v1/opinions" + (category ? `?category=${category}` : "")
    ),
  update: (id: string, body: { category?: string; note?: string; tags?: string[] }) =>
    api<{ status: string; id: string }>(`/api/v1/opinions/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  delete: (id: string) =>
    api<{ status: string; id: string }>(`/api/v1/opinions/${id}`, {
      method: "DELETE",
    }),
};
