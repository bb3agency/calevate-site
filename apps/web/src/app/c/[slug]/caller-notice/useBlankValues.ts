"use client";

import { useCallback, useEffect, useState } from "react";

import type { BlankValues } from "@/lib/noticeDraft/blanks";

/**
 * What the owner has typed into the draft's blanks, kept in THIS BROWSER only.
 *
 * Nothing here reaches our servers: the notice is the client's document and its filled
 * version is theirs to copy, download or print. Local storage only spares them retyping
 * after a reload. It is a convenience, so every access is in try/catch (a private window
 * or blocked site data throws) and the screen works the same without it.
 *
 * Not persisted in a support "view as" session (`persist` false): those words are the
 * client's, and an operator's browser is not where they should be left behind.
 */
export function useBlankValues(orgSlug: string, persist: boolean) {
  const storageKey = `calevate:caller-notice:${orgSlug}`;
  const [values, setValues] = useState<BlankValues>({});

  // Read after mount, not during render: the server render has no storage, and reading
  // it in the initialiser would hydrate a different tree from the one the server sent.
  useEffect(() => {
    if (!persist) return;
    try {
      const stored = window.localStorage.getItem(storageKey);
      const parsed: unknown = stored ? JSON.parse(stored) : null;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const clean: BlankValues = {};
        for (const [key, value] of Object.entries(parsed)) {
          if (typeof value === "string") clean[key] = value;
        }
        setValues(clean);
      }
    } catch {
      // Unreadable storage is the same as empty storage.
    }
  }, [storageKey, persist]);

  const write = useCallback(
    (next: BlankValues) => {
      if (!persist) return;
      try {
        if (Object.values(next).some((value) => value.trim())) {
          window.localStorage.setItem(storageKey, JSON.stringify(next));
        } else {
          window.localStorage.removeItem(storageKey);
        }
      } catch {
        // A full or blocked store loses the convenience, never the typing.
      }
    },
    [storageKey, persist],
  );

  const set = useCallback(
    (key: string, value: string) => {
      setValues((current) => {
        const next = { ...current, [key]: value };
        write(next);
        return next;
      });
    },
    [write],
  );

  const clear = useCallback(() => {
    setValues({});
    write({});
  }, [write]);

  return { values, set, clear };
}
