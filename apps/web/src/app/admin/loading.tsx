/**
 * What an operator sees the moment they open another console screen.
 *
 * Every route is dynamic (`app/layout.tsx` `dynamic = "force-dynamic"`), so without a
 * loading boundary Next keeps the old screen on display until the server has answered for
 * the new one, and a click looks ignored for a round trip. With it, Next prefetches the
 * shell down to this boundary and swaps to it at once (nextjs.org/docs/app/api-reference/
 * file-conventions/loading). It renders inside the shell's rail, so the sidebar and header
 * stay put.
 */
import { Skeleton } from "@/components/ui";

export default function AdminScreenLoading() {
  return <Skeleton rows={8} label="Opening this screen" />;
}
