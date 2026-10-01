/**
 * Save text the browser already holds as a file. The blob dance `lib/api/dataRights.ts::
 * downloadJson` performs, for text: in the document, then revoked a tick later, because a
 * detached anchor is a no-op in some browsers and revoking synchronously can cancel the save.
 */
export function downloadText(text: string, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
