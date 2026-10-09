import { apiRequest, type Session } from "./client";

/** The browser refused to open a tab for the document, so nothing was shown. */
export class ViewerBlockedError extends Error {
  constructor() {
    super(
      "Your browser blocked the new tab, so the file was not opened. Allow pop-ups for this site, then try again.",
    );
    this.name = "ViewerBlockedError";
  }
}

/**
 * Open a file only an authenticated request can read (it needs the session headers, so a
 * plain link cannot reach it) in a new tab, from memory. Shared by the operator's KYC
 * review and the client's own certificate.
 *
 * The tab is opened BEFORE the fetch, in the click's own task: a `window.open` after an
 * `await` is no longer a user gesture, and pop-up blockers drop it without a word. So
 * call this straight from the click handler. A failed read closes the empty tab and throws.
 */
export async function openProtectedFile(session: Session, path: string): Promise<void> {
  const viewer = window.open("", "_blank");
  if (viewer === null) throw new ViewerBlockedError();
  // Opened without `noopener` so its location can be set below; cut the back-reference now.
  viewer.opener = null;
  try {
    const blob = await apiRequest<Blob>(session, path, { responseType: "blob" });
    const url = URL.createObjectURL(blob);
    viewer.location.href = url;
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    viewer.close();
    throw error;
  }
}
