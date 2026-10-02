"use client";

import { ConfigScreen } from "./ConfigScreen";

/** The route is chrome only (UX-DOCTRINE §6); the screen lives in `ConfigScreen`. */
export default function OpsConfigPage() {
  return <ConfigScreen />;
}
