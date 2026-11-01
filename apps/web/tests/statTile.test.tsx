import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatTile } from "@/components/ui";

describe("StatTile figure", () => {
  it("never breaks inside a long figure; it steps down a size instead", () => {
    render(<StatTile label="Spend" value="₹9,19,87,65,43,210" />);
    const figure = screen.getByText("₹9,19,87,65,43,210");
    expect(figure.className).not.toContain("overflow-wrap:anywhere");
    expect(figure.className).toContain("[overflow-wrap:normal]");
    expect(figure.className).toContain("text-base");
  });

  it("keeps the full size for an ordinary figure", () => {
    render(<StatTile label="Calls" value="1,250" />);
    expect(screen.getByText("1,250").className).toContain("text-xl");
  });
});
