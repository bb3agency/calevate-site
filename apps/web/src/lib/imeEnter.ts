/**
 * Is this key press part of an input-method composition rather than a key of its own?
 *
 * Telugu and Hindi are typed through an IME (Google Input Tools, the Windows phonetic
 * keyboards, Gboard's transliteration): Latin letters build a candidate word, and Enter
 * PICKS the candidate. That Enter still reaches `keydown`, so a handler that treats every
 * Enter as "send" or "save" fires mid-word — it sends or saves the half-composed text, and
 * the word the person chose then lands in a box that has just been cleared.
 *
 * `isComposing` is the standard signal; `keyCode === 229` is the one Chrome and Safari give
 * for the composition's own keys (and for the committing Enter in Safari, where
 * `isComposing` is already false by then). Native form submission already skips composing
 * keys, so only hand-written Enter handlers need this.
 * https://developer.mozilla.org/en-US/docs/Web/API/KeyboardEvent/isComposing
 */
export function isImeComposing(event: { nativeEvent?: KeyboardEvent; isComposing?: boolean; keyCode?: number }): boolean {
  const native = event.nativeEvent ?? event;
  return Boolean(native.isComposing) || native.keyCode === 229;
}
