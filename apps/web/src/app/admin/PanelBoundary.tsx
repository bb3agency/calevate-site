"use client";

import { Component, type ReactNode } from "react";

import { TEXT_ACTION } from "@/components/console/section";
import { NoticeBox } from "@/components/ui";

/**
 * One panel's crash stays inside that panel.
 *
 * Without this the nearest boundary is `app/admin/error.tsx`, which replaces the whole
 * screen: a single panel reading a field an older API did not send blanked a client's
 * overview, holds and credit included. The web and the API deploy separately, so that skew
 * is an ordinary deploy state, not an edge case.
 */
export class PanelBoundary extends Component<
  { title: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error): void {
    console.error("[calevate] admin panel stopped", {
      panel: this.props.title,
      name: error.name,
      message: error.message,
    });
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <NoticeBox
        tone="stop"
        role="alert"
        title={`${this.props.title} could not be shown.`}
        action={
          <button
            type="button"
            className={TEXT_ACTION}
            onClick={() => this.setState({ failed: false })}
          >
            Try again
          </button>
        }
      >
        The rest of this page still works. Reload if it keeps happening.
      </NoticeBox>
    );
  }
}
