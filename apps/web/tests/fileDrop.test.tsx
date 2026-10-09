import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FileDrop, formatFileSize } from "@/components/fileDrop";

/**
 * The kit's one file control. What is pinned is what the browser's own input got wrong
 * or never had: a name a screen reader announces, the rules said before a file is chosen,
 * an inline refusal for a DROPPED file (a drop bypasses `accept`), and a Remove per file.
 */

const pdf = (name = "certificate.pdf", bytes = 2048) =>
  new File(["x".repeat(bytes)], name, { type: "application/pdf" });

describe("FileDrop", () => {
  it("is a real, focusable file input named by its label and described by its rules", () => {
    render(<FileDrop label="Evidence" hint="PDF, up to 5 MB." accept="application/pdf" onFiles={() => {}} />);
    const input = screen.getByLabelText("Evidence") as HTMLInputElement;
    expect(input.type).toBe("file");
    expect(input.className).toContain("sr-only");
    expect(input.hasAttribute("capture")).toBe(false);
    expect(document.getElementById(input.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
      "PDF, up to 5 MB.",
    );
  });

  it("refuses a dropped file of the wrong kind or size inline, and passes a good one on", () => {
    const onFiles = vi.fn();
    render(
      <FileDrop label="Evidence" hint="PDF" accept="application/pdf" maxBytes={4096} onFiles={onFiles} />,
    );
    const zone = screen.getByText("Evidence").closest("label")!;
    const png = new File(["x"], "photo.png", { type: "image/png" });
    fireEvent.drop(zone, { dataTransfer: { files: [png] } });
    expect(screen.getByRole("alert").textContent).toBe("That kind of file cannot be sent here.");
    fireEvent.drop(zone, { dataTransfer: { files: [pdf("big.pdf", 8192)] } });
    expect(screen.getByRole("alert").textContent).toBe("That file is 8 KB, over the 4 KB limit.");
    expect(onFiles).not.toHaveBeenCalled();
    fireEvent.drop(zone, { dataTransfer: { files: [pdf()] } });
    expect(onFiles).toHaveBeenCalledWith([expect.objectContaining({ name: "certificate.pdf" })]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("uses the caller's rule when it gives one", () => {
    render(
      <FileDrop label="Certificate" hint="" accept=".pdf" validate={() => "Choose a PDF, JPEG or PNG file."} onFiles={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText("Certificate"), { target: { files: [pdf()] } });
    expect(screen.getByRole("alert").textContent).toBe("Choose a PDF, JPEG or PNG file.");
  });

  it("lists chosen files with their size and a Remove each", () => {
    const onRemove = vi.fn();
    render(
      <FileDrop
        label="Evidence"
        hint=""
        accept="application/pdf"
        multiple
        files={[pdf("a-very-long-scanner-filename-20261009-000123.pdf")]}
        onRemove={onRemove}
        onFiles={() => {}}
      />,
    );
    expect(screen.getByText("PDF · 2 KB")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove a-very-long-scanner-filename-20261009-000123.pdf" }));
    expect(onRemove).toHaveBeenCalledWith(0);
  });

  it("formats sizes the way a person reads them", () => {
    expect(formatFileSize(512)).toBe("512 bytes");
    expect(formatFileSize(3_565_158)).toBe("3.4 MB");
  });
});
