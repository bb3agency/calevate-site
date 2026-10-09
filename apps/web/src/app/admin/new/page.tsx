"use client";

import { NewClientScreen } from "./NewClientScreen";

/**
 * New client (D-695): the business's name, web address and type, and the owner to
 * invite. The route is chrome and nothing else (UX-DOCTRINE §6).
 *
 * NO `<h1>`: the admin shell derives the page title from the nav list it renders.
 */
export default function NewClientPage() {
  return <NewClientScreen />;
}
