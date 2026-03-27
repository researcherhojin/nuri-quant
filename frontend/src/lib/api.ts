export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export async function fetchAPI<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    next: { revalidate: 60 }, // 60초 캐시
  });
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
  return res.json();
}
