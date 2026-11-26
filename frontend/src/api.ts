let csrf = "";

export function setCsrfToken(token: string) {
  csrf = token;
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      "X-CSRFToken": csrf,
      ...init.headers,
    },
  });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : null;
  if (!response.ok)
    throw new ApiError(
      response.status,
      body?.error?.message ||
        (response.status === 403
          ? "This action needs current access. Sign in again if your session expired."
          : `Request failed (${response.status}).`),
    );
  return body;
}
