/**
 * The one sentence a client reads about GST, on every console and marketing surface (D-659).
 *
 * It is the same string as `apps/api/billing/gst.py::GST_STATUS_SENTENCE`, which the server
 * puts on the statement's tax note and on the payment receipt; `tests/gst_status_test.py`
 * fails when the two copies differ. Reword it in both places in one change, never here alone.
 *
 * NOT for the legal pages: `src/lib/legal/*` is hash-guarded and states the position in its
 * own revisioned words.
 */
export const GST_STATUS_SENTENCE =
  "Calevate is a sole proprietorship below the GST registration threshold, so it is not registered for GST, charges no GST and does not issue tax invoices.";
