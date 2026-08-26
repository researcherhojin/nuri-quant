"use client";

/**
 * 최상위 에러 바운더리 — layout.tsx 레벨 에러 캐치.
 */

import { ERRORS } from "@/lib/strings";
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="ko" className="dark h-full antialiased">
      <body className="min-h-full flex items-center justify-center bg-background text-foreground">
        <div className="text-center space-y-4 p-8">
          <div className="text-4xl">!</div>
          <h1 className="text-xl font-bold">{ERRORS.GENERIC_TITLE}</h1>
          <p className="text-sm text-muted-foreground max-w-md">{error.message}</p>
          <button
            onClick={reset}
            className="px-4 py-2 text-sm bg-muted hover:bg-accent rounded-lg transition-colors"
          >
            {ERRORS.RETRY}
          </button>
        </div>
      </body>
    </html>
  );
}
