import Link from "next/link";

/**
 * Root of `app.calevate.tech`.
 *
 * There is deliberately no marketing content here: client URLs are slug-based
 * (D-10, `/c/<slug>`) and the signed-in redirect lands on the workspace. The
 * self-serve signup flow that would otherwise live at this path is M2 (D-34), so
 * this page says what it is rather than pretending to be a product tour.
 */
export default function Home() {
  const devSlug = process.env.NEXT_PUBLIC_DEV_ORG_SLUG;
  return (
    <div className="mx-auto flex min-h-full max-w-xl flex-col justify-center gap-6 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">Calevate</h1>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          AI phone agents for Indian businesses. Your workspace lives at a URL your
          account manager gave you.
        </p>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
        <p className="font-medium text-slate-800 dark:text-slate-200">Open your workspace</p>
        <p className="mt-1 text-slate-600 dark:text-slate-400">
          Go to <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">/c/your-slug</code>.
        </p>
        {devSlug && (
          <Link
            href={`/c/${devSlug}`}
            className="mt-3 inline-block rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
          >
            Open {devSlug}
          </Link>
        )}
      </div>
    </div>
  );
}
