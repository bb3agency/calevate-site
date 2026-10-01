import type { ReactNode } from "react";

import { Card } from "@/components/ui";

/**
 * DEPRECATED — use `<Card density="compact" info={…}>` (`components/ui.tsx`). The compact
 * panel was folded into `Card` so there is one panel primitive; this wrapper only keeps a
 * screen that adopted it during the round-2 redesign compiling until it moves, and is
 * deleted with its last caller.
 */
export function Panel({
  title,
  info,
  action,
  children,
  className,
  bodyClassName,
}: {
  title: string;
  info?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <Card
      density="compact"
      title={title}
      info={info}
      action={action}
      className={className}
      bodyClassName={bodyClassName}
    >
      {children}
    </Card>
  );
}
