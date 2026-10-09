"use client";

/**
 * "Continue with Google" for the client realm (D-703), with the "or" rule under it.
 *
 * Renders nothing until the API says Google sign-in is switched on for this deployment
 * (`GET /v1/auth/client/sign-in-options`), so a page never offers a button that cannot
 * work. Google's branding guidelines ask for their own "G" mark and the wording
 * "Continue with Google"; the mark is inlined rather than fetched from Google.
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { SECONDARY_BUTTON } from "@/components/ui";
import { AuthProblemNotice } from "@/components/authn/fields";
import { readSignInOptions, startGoogleSignIn } from "@/lib/authn/clientAuthn";

export function useSignInOptions() {
  return useQuery({
    queryKey: ["authn", "client", "sign-in-options"],
    queryFn: readSignInOptions,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 48 48" className="h-[18px] w-[18px] shrink-0">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export function GoogleSignIn({
  next,
  invitationToken,
  label = "Continue with Google",
  divider = "or use your email",
}: {
  /** The console page to return to afterwards, when the person was sent here from one. */
  next?: string | null;
  /** An invitation to accept with the Google account, when this is the invitation page. */
  invitationToken?: string | null;
  label?: string;
  /** The rule between this button and the email form; null for none. */
  divider?: string | null;
}) {
  const options = useSignInOptions();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (!options.data?.google) return null;

  return (
    <div className="space-y-4">
      <button
        type="button"
        className={`${SECONDARY_BUTTON} w-full justify-center py-2.5 text-ink`}
        disabled={pending}
        onClick={async () => {
          setPending(true);
          setError(null);
          try {
            await startGoogleSignIn({ next, invitationToken });
          } catch (cause) {
            setError(cause);
            setPending(false);
          }
        }}
      >
        <GoogleMark />
        {pending ? "Opening Google…" : label}
      </button>
      <AuthProblemNotice error={error} />
      {divider && (
        <div className="flex items-center gap-3 text-xs text-ink-faint" role="separator">
          <span className="h-px flex-1 bg-line" />
          {divider}
          <span className="h-px flex-1 bg-line" />
        </div>
      )}
    </div>
  );
}
