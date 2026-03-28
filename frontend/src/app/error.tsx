"use client";

/**
 * 라우트 레벨 에러 바운더리 — API 실패 등 페이지 에러 캐치.
 * layout은 유지하고 페이지 영역만 에러 UI로 교체.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const isApiError = error.message.includes("API") || error.message.includes("fetch");

  return (
    <div className="flex flex-col items-center justify-center py-20 space-y-4">
      <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center">
        <span className="text-red-400 text-lg font-bold">!</span>
      </div>
      <h2 className="text-lg font-semibold">
        {isApiError ? "API connection failed" : "Something went wrong"}
      </h2>
      <p className="text-sm text-muted-foreground max-w-md text-center">
        {isApiError
          ? "Backend API is not responding. Make sure the server is running (make api)."
          : error.message}
      </p>
      <button
        onClick={reset}
        className="px-4 py-2 text-sm bg-muted hover:bg-accent rounded-lg transition-colors"
      >
        Retry
      </button>
    </div>
  );
}
