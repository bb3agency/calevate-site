import { redirect } from "next/navigation";

type Params = Promise<{ slug: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Where a retired client route sends its reader: `/c/{slug}{path}`, with every query
 * parameter the old link carried. The file of a retired route stays so a bookmark, an email
 * already sent or an old link still lands; a server `redirect()` rather than a client
 * navigation, so nothing paints before the hop.
 *
 * The query is carried because `view=admin` is what keeps an operator's view-as session on
 * the next page (`lib/api/session.tsx`); dropping it would hand the operator a client session
 * there. `set` names the parameters the redirect itself decides (a tab, a mode), which
 * replace any the old link carried.
 */
export async function redirectWithin(
  params: Params,
  searchParams: SearchParams,
  path: string,
  set: Record<string, string> = {},
): Promise<never> {
  const { slug } = await params;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (value === undefined || Object.hasOwn(set, key)) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  for (const [key, value] of Object.entries(set)) query.set(key, value);
  const carried = query.toString();
  redirect(`/c/${encodeURIComponent(slug)}${path}${carried ? `?${carried}` : ""}`);
}
