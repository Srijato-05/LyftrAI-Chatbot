import type { ChatResponse, HealthResponse } from "./types";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL as string | undefined;
export const API_BASE_URL = (RAW_BASE && RAW_BASE.trim() ? RAW_BASE.trim() : "http://localhost:8000").replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function extractDetail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (first && typeof first === "object" && "msg" in first) {
        return String((first as { msg: unknown }).msg);
      }
    }
  }
  return `Request failed with status ${status}`;
}

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, extractDetail(data, res.status));
  }
  return data as HealthResponse;
}

export async function sendChat(params: {
  session_id: string;
  message: string;
  system_prompt?: string;
}): Promise<ChatResponse> {
  const payload: Record<string, string> = {
    session_id: params.session_id,
    message: params.message,
  };
  if (params.system_prompt && params.system_prompt.trim()) {
    payload.system_prompt = params.system_prompt.trim();
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError(0, "Could not reach the backend server.");
  }

  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, extractDetail(data, res.status));
  }
  return data as ChatResponse;
}

