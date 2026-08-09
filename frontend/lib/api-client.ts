export const BACKEND_URL: string =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export type BackendClient = {
  baseUrl: string;
};

export function createApiClient(baseUrl: string = BACKEND_URL): BackendClient {
  return { baseUrl };
}
