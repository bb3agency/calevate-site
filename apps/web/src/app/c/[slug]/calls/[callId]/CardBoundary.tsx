"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * One card of the call screen, isolated (L3-06). A card that throws while rendering (a
 * field the server did not send during a deploy, when the web is newer than the API) shows
 * one short line in its place and the rest of the call stays readable, instead of the
 * realm boundary (`c/[slug]/error.tsx`) replacing the whole screen. React catches render
 * errors only in a class component with `getDerivedStateFromError`.
 */
export class CardBoundary extends Component<{ name: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The operator's line: which card, and the error's name and message. Never the call's
    // data, which may hold a caller's details.
    console.error("[calevate] call card failed", {
      card: this.props.name,
      name: error.name,
      message: error.message,
      stack: info.componentStack?.split("\n").slice(0, 3).join("\n"),
    });
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <p role="status" className="text-meta text-ink-muted">
        {this.props.name} could not be shown. Reload the page to try again.
      </p>
    );
  }
}
