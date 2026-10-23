"use client";

import Link from "next/link";

import { TEXT_ACTION } from "@/components/console/section";
import { NoticeBox, formatISTDay } from "@/components/ui";
import type { CampaignNumber } from "@/lib/api/campaigns";

/**
 * A HELD NUMBER (D-860): the account's credit has been below zero for too long, so calls to
 * a number it rents have stopped and it will be given up on a date unless the owner tops up.
 *
 * The date is the headline because it is the one fact the owner can act against; topping up
 * is the whole fix, so it is the only action. A closed account cannot sign in, so the top-up
 * is the only way back this screen can offer. `release_at` is null for the moment between a
 * hold starting and its date being worked out, and the sentence then says so rather than
 * printing a placeholder date.
 */
export function HeldNumberNotice({
  numbers,
  topUpHref,
}: {
  numbers: CampaignNumber[];
  topUpHref: string;
}) {
  const held = numbers.filter((number) => number.held);
  if (held.length === 0) return null;
  const days = held
    .map((number) => number.release_at)
    .filter((at): at is string => typeof at === "string")
    .sort();
  const first = formatISTDay(days[0]);
  const plural = held.length > 1;
  const title = first
    ? `Calls stopped. ${plural ? "The first of your numbers is released" : "Released"} on ${first} unless you top up.`
    : "Calls stopped. Your number will be released soon unless you top up.";
  return (
    <NoticeBox
      tone="stop"
      role="alert"
      title={title}
      action={
        <Link href={topUpHref} className={TEXT_ACTION}>
          Add credit
        </Link>
      }
    >
      {plural ? "Nobody answers these numbers" : "Nobody answers this number"} and no rent is
      charged meanwhile. Once a number is released it goes back to the phone company and we
      cannot get it back.
    </NoticeBox>
  );
}

/** The same notice for one number, on its own card. */
export function HeldNumberLine({ number, topUpHref }: { number: CampaignNumber; topUpHref: string }) {
  if (!number.held) return null;
  const day = formatISTDay(number.release_at);
  return (
    <NoticeBox
      tone="stop"
      role="status"
      title={day ? `Calls stopped. Released on ${day} unless you top up.` : "Calls stopped. Released soon unless you top up."}
      action={
        <Link href={topUpHref} className={TEXT_ACTION}>
          Add credit
        </Link>
      }
    />
  );
}
