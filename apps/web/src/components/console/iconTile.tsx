import type { ComponentType, SVGProps } from "react";
import { ServiceLogo, serviceKeyFor } from "./serviceLogo";

/**
 * THE ONE ICON FRAME FOR A ROW THAT STANDS FOR A THING (REDESIGN-2): a 40px rounded square,
 * hairline, white, holding a 24px mark. A connected service shows its own logo; anything
 * else shows a generic line icon in ink-muted, in the same frame, so a list of actions or
 * accounts reads as one column whether or not a brand is involved.
 *
 * `service` wins when it names a service we hold a logo for; otherwise `icon` is drawn.
 * Inline beside text (an account line, a select) use `ServiceLogo` at 20px instead: a
 * frame around a 20px mark inside a sentence is noise.
 */
export function IconTile({
  service,
  icon: Icon,
  className = "",
}: {
  service?: string | null;
  icon?: ComponentType<SVGProps<SVGSVGElement>>;
  className?: string;
}) {
  const hasLogo = serviceKeyFor(service) !== null;
  return (
    <span
      aria-hidden
      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-line bg-white ${className}`}
    >
      {hasLogo ? (
        <ServiceLogo service={service} className="h-6 w-6" />
      ) : Icon ? (
        <Icon className="h-5 w-5 text-ink-muted" strokeWidth={1.75} />
      ) : null}
    </span>
  );
}
