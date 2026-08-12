"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiProblem } from "@/lib/api/client";

/**
 * Query defaults, chosen from the API's error contract rather than from taste.
 *
 * `retryable` on a problem+json body tells us whether a retry can possibly help —
 * a compliance refusal, a 403 or a validation failure will fail identically forever,
 * so retrying them just delays the message the user needs to read.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            retry: (failureCount, error) => {
              if (error instanceof ApiProblem) return error.retryable && failureCount < 2;
              return failureCount < 2;
            },
          },
          mutations: {
            // Never auto-retry a mutation: the expensive ones place phone calls, and
            // their safety net is the server's Idempotency-Key handling, not a client
            // guess about whether the first attempt landed.
            retry: false,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
