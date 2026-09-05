import { formatIST } from "@/components/ui";
import { walletReasonLabel, type WalletEntry } from "@/lib/api/wallet";

/**
 * The transactions a client can take away — a CSV of the wallet history on screen.
 *
 * ## Why the browser builds it, and what that costs
 *
 * The API has no statement-CSV route and this deliberately does not add one. The rows are
 * ALREADY in the browser — `GET /v1/billing/wallet/ledger` fetched them for the table this
 * button sits under — so a second route would be a second way to produce one document, a
 * second permission to keep in step, and a second bound to register. What it buys instead
 * is honesty about scope: this file is exactly the rows on screen and the caller says so
 * in the sentence beside the button, rather than implying a complete account history.
 *
 * The MONTHLY statement is a different document and is not this: `GET /v1/billing/invoice`
 * builds a bill of supply for an IST month, it is rendered on the same tab, and the browser
 * prints it. Two documents, two questions — "what moved on my wallet" and "what did this
 * month cost" — and neither is a re-derivation of the other.
 *
 * ## MONEY IS NEVER PARSED (hard rule 7 reaches the browser)
 *
 * Every amount is written into the file as the exact decimal STRING the server sent.
 * Nothing here calls `Number()`, sums a column, or reformats a figure with a thousands
 * separator: a spreadsheet has to be able to add this column up, and `₹1,234.00` is text
 * to Excel while `1234.00` is a number. The rupee sign therefore lives in the HEADER
 * ("Amount (INR)"), never in a cell.
 *
 * ## RFC 4180, and the one attack this file has to survive
 *
 * Fields are quoted and internal quotes doubled per RFC 4180 §2. On top of that, a cell
 * beginning `=`, `+`, `-` or `@` is prefixed with a single quote: those are the four
 * leaders Excel, LibreOffice and Sheets treat as the start of a FORMULA, and the `ref`
 * column carries text the server got from a payment provider. CSV injection (OWASP calls
 * it "CSV Injection"; it is why LibreOffice ships a formula-import prompt) is the reason —
 * a file the client opens in a spreadsheet must not be able to run anything.
 *
 * A DEBIT ALREADY CARRIES ITS MINUS SIGN, so `-42.50` would trip the same rule. Quoting
 * it as `'-42.50` would break the arithmetic this file exists for, so the escape is
 * applied ONLY to the two free-text columns (`what`, `ref`) and never to a money cell — a
 * money cell can only ever hold digits, a dot and a leading minus.
 */

/** RFC 4180 §2 quoting, plus the spreadsheet-formula guard argued in the header. */
function cell(value: string, { guardFormulas }: { guardFormulas: boolean }): string {
  const guarded =
    guardFormulas && /^[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${guarded.replace(/"/g, '""')}"`;
}

/** The header row, in the order a person reads a bank statement. */
const HEADERS = ["Date (IST)", "What", "Reference", "Amount (INR)", "Balance after (INR)"];

/**
 * The wallet entries as CSV text, newest first — the order the table shows them in, so
 * the file and the screen tell the same story from the top.
 *
 * CRLF line endings, which RFC 4180 §2 specifies and which is what Excel on Windows
 * expects; every other consumer accepts them.
 */
export function walletStatementCsv(entries: WalletEntry[]): string {
  const rows = entries.map((entry) => [
    cell(formatIST(entry.occurred_at), { guardFormulas: true }),
    cell(walletReasonLabel(entry.reason), { guardFormulas: true }),
    cell(entry.ref ?? "", { guardFormulas: true }),
    // Money: the server's own digits, never guarded and never grouped. See the header.
    cell(entry.delta_inr, { guardFormulas: false }),
    cell(entry.balance_after_inr, { guardFormulas: false }),
  ]);
  return [HEADERS.map((h) => cell(h, { guardFormulas: false })), ...rows]
    .map((row) => row.join(","))
    .join("\r\n");
}
