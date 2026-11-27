let csrf = "";

export function setCsrfToken(token: string) {
  csrf = token;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly requestId: string | null,
    public readonly code: string | null,
    public readonly details: Record<string, unknown>,
  ) {
    super(requestId ? `${message} Request ID ${requestId}.` : message);
  }
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!headers.has("X-CSRFToken")) headers.set("X-CSRFToken", csrf);
  const response = await fetch("/api/v1" + path, {
    ...init,
    credentials: "same-origin",
    headers,
  });
  const type = response.headers.get("content-type") || "";
  let body = null;
  if (type.includes("json")) {
    try {
      body = await response.json();
    } catch (error) {
      if (response.ok || init.signal?.aborted) throw error;
    }
  }
  if (!response.ok) {
    const error = body?.error;
    const requestId = response.headers.get("X-Request-ID") || error?.request_id;
    const fallback = response.status === 403
      ? "This action needs current access. Sign in again if your session expired."
      : `Request failed (${response.status}).`;
    throw new ApiError(
      response.status,
      typeof error?.message === "string" && error.message ? error.message : fallback,
      typeof requestId === "string" && /^req_[0-9a-f]{32}$/.test(requestId) ? requestId : null,
      typeof error?.code === "string" ? error.code : null,
      error?.details && typeof error.details === "object" && !Array.isArray(error.details) ? error.details : {},
    );
  }
  return body;
}
