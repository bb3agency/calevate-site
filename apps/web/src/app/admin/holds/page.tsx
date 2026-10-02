"use client";

import { HoldsScreen } from "./HoldsScreen";

/**
 * The ops work list: who is waiting on a human, and for how long. No `<h1>`: the shell
 * derives the title from the nav list (`app/admin/adminNav.ts`), so a heading here would be
 * the same words twice and a second place for them to be renamed.
 */
export default function HeldAccountsPage() {
  return <HoldsScreen />;
}
