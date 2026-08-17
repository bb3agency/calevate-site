import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { use } from "react";

import { LEGAL_DOCUMENTS, legalDocument } from "@/lib/legal";
import { LegalDocumentPage } from "@/lib/legal/document";

/**
 * One route for all eight documents, statically generated from the content module.
 *
 * A page file per document was the alternative and buys nothing: every one of them would
 * be the same three lines, and the eight-way duplication would be eight chances for one
 * page to drift out of the shared shell. `generateStaticParams` prerenders every slug, so
 * these are static HTML at build time despite the dynamic segment — which matters, because
 * a legal page that depends on a running API is a legal page that 500s during an incident.
 *
 * An unknown slug is a 404 rather than a redirect: `/legal/gdpr` should tell the reader
 * there is no such document, not silently hand them a different one.
 */
export function generateStaticParams(): { slug: string }[] {
  return LEGAL_DOCUMENTS.map((doc) => ({ slug: doc.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const doc = legalDocument(slug);
  if (!doc) return { title: "Not found — Calevate" };
  return { title: `${doc.title} — Calevate`, description: doc.summary };
}

export default function LegalDocumentRoute({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const doc = legalDocument(slug);
  if (!doc) notFound();
  return <LegalDocumentPage doc={doc} />;
}
