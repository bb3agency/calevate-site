"use client";

import { FleetSpendScreen } from "./FleetSpendScreen";

/**
 * The money board. No `<h1>` here: the shell derives the title from the nav list
 * (`app/admin/adminNav.ts`), so a heading here would repeat it.
 */
export default function FleetSpendPage() {
  return <FleetSpendScreen />;
}
