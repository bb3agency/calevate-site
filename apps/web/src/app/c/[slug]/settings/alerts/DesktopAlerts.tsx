"use client";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { SECONDARY_BUTTON } from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { turnOffDesktopAlerts, turnOnDesktopAlerts, useDesktopAlertState } from "@/lib/desktopAlerts";

/**
 * DESKTOP ALERTS on this computer (`lib/desktopAlerts.ts`): the bell's items as browser
 * notifications while the console is open. The browser's permission is asked from the
 * button and nowhere else; a denied permission is said plainly and never re-asked.
 */
export function DesktopAlerts() {
  const session = useClientSession();
  const state = useDesktopAlertState(session.orgSlug);

  return (
    <Section
      title="On this computer"
      description="While this console is open, show what needs you as a desktop notification."
    >
      <SettingRows className="border-y border-line">
        <SettingRow
          label="Desktop alerts"
          hint={
            state === "denied"
              ? "Your browser blocks notifications for this site. Allow them in the browser's site settings to use this."
              : state === "unsupported"
                ? "This browser cannot show desktop notifications."
                : "The same things as the bell: blocked calls, failed deliveries, stalled campaigns and more."
          }
          value={state === "on" ? "On" : state === "off" ? "Off" : "Not available"}
          action={
            state === "off" ? (
              <button type="button" className={SECONDARY_BUTTON} onClick={() => void turnOnDesktopAlerts(session.orgSlug)}>
                Turn on desktop alerts
              </button>
            ) : state === "on" ? (
              <button type="button" className={TEXT_ACTION} onClick={() => turnOffDesktopAlerts(session.orgSlug)}>
                Turn off
              </button>
            ) : undefined
          }
        />
      </SettingRows>
    </Section>
  );
}
