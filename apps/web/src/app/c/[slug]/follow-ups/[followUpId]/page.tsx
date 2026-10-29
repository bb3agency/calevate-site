"use client";

import { use } from "react";

import { FollowUpScreen } from "./FollowUpScreen";

/** `/c/{slug}/follow-ups/{id}`: one Follow-up's steps, the leads in it and how it went. */
export default function FollowUpPage({
  params,
}: {
  params: Promise<{ slug: string; followUpId: string }>;
}) {
  const { followUpId } = use(params);
  return <FollowUpScreen followUpId={followUpId} />;
}
