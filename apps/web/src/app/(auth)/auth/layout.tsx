import type { ReactNode } from "react";

import { SignInOptionsFromServer } from "@/components/authn/googleSignIn";
import { readSignInOptionsOnServer } from "@/lib/authn/signInOptionsServer";

/**
 * Hands the sign-in pages this deployment's sign-in options as read on the server, so
 * "Continue with Google" is on the first paint (`components/authn/googleSignIn`). It adds
 * nothing visible: `tests/a11y.test.tsx` renders each page without its layout, and those
 * pages then ask from the browser as they always did.
 */
export default async function AuthLayout({ children }: { children: ReactNode }) {
  const options = await readSignInOptionsOnServer();
  return <SignInOptionsFromServer options={options}>{children}</SignInOptionsFromServer>;
}
