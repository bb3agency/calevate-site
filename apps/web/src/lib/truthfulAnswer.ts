/**
 * The server's truthful-answer promise split at its first sentence: the guarantee, shown
 * where the notices are, and the rest (the exact answers), shown behind a tap. The words are
 * the server's either way (`compliance/disclosure.truthful_answer_promise`), so this never
 * rewords them.
 */
export function splitPromise(rule: string): { lead: string; rest: string } {
  const match = /^(.+?[.!?])\s+(\S[\s\S]*)$/.exec(rule.trim());
  return match ? { lead: match[1], rest: match[2] } : { lead: rule.trim(), rest: "" };
}
