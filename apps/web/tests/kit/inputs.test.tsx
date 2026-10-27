import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Calendar, DatePicker } from "@/components/arc/calendar";
import { ChipGroup } from "@/components/arc/chip-group";
import { Combobox } from "@/components/arc/combobox";
import type { FeedbackStatus } from "@/components/arc/feedback";
import { InlineEdit } from "@/components/arc/inline-edit";
import {
  addDays,
  addMonths,
  daysBetween,
  formatDateRange,
  isISODate,
  monthGrid,
  weekdayIndex,
} from "@/components/arc/ist-dates";
import { MoneyInput, canonicalMoney, compareMoney, groupTyped, toPaise } from "@/components/arc/money-input";
import { MultiSelect } from "@/components/arc/multi-select";
import { NumberField } from "@/components/arc/number-field";
import { PeriodToggle } from "@/components/arc/period-toggle";
import { RadioGroup } from "@/components/arc/radio-group";
import { SearchField } from "@/components/arc/search-field";
import { RangeSlider, Slider } from "@/components/arc/slider";
import { TagInput } from "@/components/arc/tag-input";

afterEach(() => {
  vi.useRealTimers();
});

describe("money is a decimal string end to end", () => {
  it("counts paise exactly, with no float anywhere", () => {
    expect(toPaise("1,25,000.50")).toBe(BigInt(12500050));
    expect(toPaise("0.1")).toBe(BigInt(10));
    expect(toPaise("12.345")).toBeNull();
    expect(compareMoney("10159.00", "9999.99")).toBe(1);
    expect(compareMoney("0.10", "0.1")).toBe(0);
    // 0.1 + 0.2 is the float trap; as paise it is exact.
    expect(compareMoney("0.30", "0.3")).toBe(0);
  });

  it("canonicalises what was typed, and refuses what is not an amount", () => {
    expect(canonicalMoney("1,25,000")).toBe("125000.00");
    expect(canonicalMoney("12.5")).toBe("12.50");
    expect(canonicalMoney("007")).toBe("7.00");
    expect(canonicalMoney("")).toBe("");
    expect(canonicalMoney("12.5", false)).toBeNull();
    expect(canonicalMoney("1.2.3")).toBeNull();
  });

  it("groups the Indian way while typing", () => {
    expect(groupTyped("125000")).toBe("1,25,000");
    expect(groupTyped("12345678.5")).toBe("1,23,45,678.5");
    expect(groupTyped("0012")).toBe("12");
    expect(groupTyped(".5")).toBe("0.5");
  });

  function Money({ onValue, min, paise = true }: { onValue: (v: string) => void; min?: string; paise?: boolean }) {
    const [value, setValue] = useState("");
    return (
      <MoneyInput
        label="Add credit"
        value={value}
        min={min}
        paise={paise}
        onChange={(next) => {
          setValue(next);
          onValue(next);
        }}
      />
    );
  }

  it("emits the canonical string and shows lakh grouping", () => {
    const onValue = vi.fn();
    render(<Money onValue={onValue} />);
    const box = screen.getByLabelText("Add credit") as HTMLInputElement;
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "125000.5" } });
    expect(onValue).toHaveBeenLastCalledWith("125000.50");
    expect(box.value).toBe("1,25,000.5");
    fireEvent.blur(box);
    expect(box.value).toBe("1,25,000.50");
  });

  it("refuses a keystroke that is not an amount, and a third decimal", () => {
    const onValue = vi.fn();
    render(<Money onValue={onValue} />);
    const box = screen.getByLabelText("Add credit") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "12a" } });
    fireEvent.change(box, { target: { value: "12.345" } });
    expect(onValue).not.toHaveBeenCalled();
    expect(box.value).toBe("");
  });

  it("says the limit on leaving the box, not while typing", () => {
    render(<Money onValue={() => {}} min="500.00" paise={false} />);
    const box = screen.getByLabelText("Add credit");
    fireEvent.change(box, { target: { value: "100" } });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.blur(box);
    expect(screen.getByRole("alert").textContent).toBe("Enter at least ₹500.");
    expect(box.getAttribute("aria-invalid")).toBe("true");
  });
});

describe("dates are India calendar days", () => {
  it("does calendar arithmetic without a zone", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2028-01-31", 1)).toBe("2028-02-29");
    expect(daysBetween("2026-11-01", "2026-11-07")).toBe(7);
    expect(isISODate("2026-02-30")).toBe(false);
    expect(isISODate("2026-02-28")).toBe(true);
  });

  it("starts weeks on Monday", () => {
    expect(weekdayIndex("2026-11-02")).toBe(0); // a Monday
    expect(weekdayIndex("2026-11-08")).toBe(6); // a Sunday
    const grid = monthGrid("2026-11-15");
    expect(grid).toHaveLength(6);
    expect(weekdayIndex(grid[0][0])).toBe(0);
    expect(grid.flat()).toContain("2026-11-01");
  });

  it("writes a range compactly", () => {
    expect(formatDateRange("2026-11-03", "2026-11-09")).toBe("3 Nov – 9 Nov 2026");
    expect(formatDateRange("2026-12-28", "2027-01-03")).toBe("28 Dec 2026 – 3 Jan 2027");
  });

  it("moves through the grid by keyboard and will not pick a disabled day", async () => {
    const onSelect = vi.fn();
    render(<Calendar selected="2026-11-10" initialMonth="2026-11-10" min="2026-11-05" onSelect={onSelect} />);
    const start = screen.getByRole("button", { name: /Tuesday, 10 November 2026/ });
    expect(start.getAttribute("tabindex")).toBe("0");
    start.focus();
    fireEvent.keyDown(start, { key: "ArrowRight" });
    await waitFor(() => expect(document.activeElement?.getAttribute("aria-label")).toMatch(/11 November 2026/));
    fireEvent.keyDown(document.activeElement as Element, { key: "PageDown" });
    await waitFor(() => expect(document.activeElement?.getAttribute("aria-label")).toMatch(/11 December 2026/));
    const early = screen.queryByRole("button", { name: /Monday, 2 November 2026/ });
    expect(early).toBeNull(); // the grid is on December now
    fireEvent.keyDown(document.activeElement as Element, { key: "PageUp" });
    const disabled = await screen.findByRole("button", { name: /Monday, 2 November 2026/ });
    expect(disabled.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(disabled);
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Friday, 20 November 2026/ }));
    expect(onSelect).toHaveBeenCalledWith("2026-11-20");
  });

  it("labels the picker with its field and shows the chosen day", () => {
    render(<DatePicker label="Campaign starts" value="2026-11-20" onChange={() => {}} />);
    const trigger = screen.getByRole("button", { name: "Campaign starts" });
    expect(trigger.textContent).toContain("20 Nov 2026");
  });
});

describe("number field", () => {
  function Counter({ max = 10 }: { max?: number }) {
    const [value, setValue] = useState<number | null>(3);
    return <NumberField label="Calls at the same time" min={1} max={max} value={value} onChange={setValue} />;
  }

  it("steps by the arrow keys and holds the limits", () => {
    render(<Counter />);
    const box = screen.getByRole("spinbutton", { name: "Calls at the same time" }) as HTMLInputElement;
    fireEvent.keyDown(box, { key: "ArrowUp" });
    expect(box.getAttribute("aria-valuenow")).toBe("4");
    fireEvent.keyDown(box, { key: "End" });
    expect(box.getAttribute("aria-valuenow")).toBe("10");
    fireEvent.keyDown(box, { key: "ArrowUp" });
    expect(box.getAttribute("aria-valuenow")).toBe("10");
    expect(screen.getByRole("button", { name: "Increase Calls at the same time" }).getAttribute("aria-disabled")).toBe("true");
  });

  it("pulls typing past a limit back and says so", () => {
    render(<Counter />);
    const box = screen.getByRole("spinbutton") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "40" } });
    fireEvent.blur(box);
    expect(box.getAttribute("aria-valuenow")).toBe("10");
    expect(screen.getByRole("alert").textContent).toContain("Kept to 10");
  });
});

describe("search field", () => {
  it("sends the settled query once, at once on Enter, and Escape clears", () => {
    vi.useFakeTimers();
    const onSearch = vi.fn();
    function Box() {
      const [value, setValue] = useState("");
      return <SearchField label="Search leads" value={value} onValueChange={setValue} onSearch={onSearch} />;
    }
    render(<Box />);
    const box = screen.getByRole("searchbox", { name: "Search leads" }) as HTMLInputElement;
    fireEvent.change(box, { target: { value: "ra" } });
    fireEvent.change(box, { target: { value: "ravi" } });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(onSearch).toHaveBeenCalledTimes(1);
    expect(onSearch).toHaveBeenLastCalledWith("ravi");
    fireEvent.change(box, { target: { value: "ravi k" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSearch).toHaveBeenLastCalledWith("ravi k");
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(onSearch).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(box, { key: "Escape" });
    expect(box.value).toBe("");
    expect(onSearch).toHaveBeenLastCalledWith("");
  });
});

describe("combobox", () => {
  const OPTIONS = [
    { value: "a", label: "Sri Lakshmi Traders" },
    { value: "b", label: "Vijaya Motors" },
    { value: "c", label: "Anand Realty" },
  ];

  it("filters by typing and picks with Enter; the all row clears", () => {
    const onChange = vi.fn();
    render(<Combobox label="Client" allLabel="All clients" options={OPTIONS} value={null} onChange={onChange} />);
    const box = screen.getByRole("combobox", { name: "Client" });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "moto" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("names an empty search", () => {
    render(<Combobox label="Client" options={OPTIONS} value={null} onChange={() => {}} />);
    const box = screen.getByRole("combobox", { name: "Client" });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "zzz" } });
    expect(screen.getByRole("listbox").textContent).toContain("Nothing matches “zzz”");
  });
});

describe("chips, tags, radios and the period", () => {
  it("toggles one chip at a time and clears with All", () => {
    const onChange = vi.fn();
    render(
      <ChipGroup mode="single" label="Outcome" allLabel="All" chips={[{ value: "won", label: "Won" }]} value="won" onChange={onChange} />,
    );
    expect(screen.getByRole("button", { name: "Won" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Won" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("keeps the caller's chip order in multiple mode", () => {
    const onChange = vi.fn();
    const chips = [
      { value: "a", label: "A" },
      { value: "b", label: "B" },
    ];
    render(<ChipGroup mode="multiple" label="Pick" chips={chips} value={["b"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "A" }));
    expect(onChange).toHaveBeenLastCalledWith(["a", "b"]);
  });

  it("adds a tag on Enter, refuses a duplicate in words, and removes the last on Backspace", () => {
    function Tags() {
      const [value, setValue] = useState(["Interested"]);
      return <TagInput label="Choices" value={value} onChange={setValue} />;
    }
    render(<Tags />);
    const box = screen.getByRole("combobox", { name: "Choices" });
    fireEvent.change(box, { target: { value: "Call back" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(screen.getByRole("button", { name: "Remove Call back" })).toBeTruthy();
    fireEvent.change(box, { target: { value: "interested" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(screen.getByRole("alert").textContent).toContain("already in the list");
    fireEvent.change(box, { target: { value: "" } });
    fireEvent.keyDown(box, { key: "Backspace" });
    expect(screen.queryByRole("button", { name: "Remove Call back" })).toBeNull();
  });

  it("chooses one radio and says the group's error", () => {
    const onChange = vi.fn();
    render(
      <RadioGroup
        label="Voice"
        options={[
          { value: "clear", label: "Clear" },
          { value: "studio", label: "Studio" },
        ]}
        value={null}
        onChange={onChange}
        error="Choose a voice."
      />,
    );
    expect(screen.getByRole("radiogroup", { name: "Voice" }).getAttribute("aria-invalid")).toBe("true");
    fireEvent.click(screen.getByRole("radio", { name: "Studio" }));
    expect(onChange).toHaveBeenCalledWith("studio");
  });

  it("switches the period between this month and all time", () => {
    const onChange = vi.fn();
    render(<PeriodToggle value="month" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "All time" }));
    expect(onChange).toHaveBeenCalledWith("all");
  });

  it("summarises a multi-select and chooses all", async () => {
    const onChange = vi.fn();
    render(
      <MultiSelect
        label="Outcomes"
        emptyLabel="Any outcome"
        options={[
          { value: "a", label: "Booked" },
          { value: "b", label: "Call back" },
        ]}
        value={[]}
        onChange={onChange}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Outcomes" });
    expect(trigger.textContent).toContain("Any outcome");
    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole("button", { name: "Choose all" }));
    expect(onChange).toHaveBeenCalledWith(["a", "b"]);
  });
});

describe("sliders", () => {
  it("speaks the words, not the symbol", () => {
    render(
      <Slider label="Speed" min={0} max={10} value={6} onChange={() => {}} valueText={() => "1.20×"} spokenText={() => "1.20 times normal"} />,
    );
    expect(screen.getByRole("slider", { name: "Speed" }).getAttribute("aria-valuetext")).toBe("1.20 times normal");
  });

  it("will not let the two ends of a range cross", () => {
    const onChange = vi.fn();
    render(<RangeSlider label="Calling hours" min={9} max={21} value={[10, 12]} onChange={onChange} />);
    fireEvent.change(screen.getByRole("slider", { name: "Calling hours: From" }), { target: { value: "15" } });
    expect(onChange).toHaveBeenLastCalledWith([12, 12]);
  });
});

describe("inline edit follows the feedback standard", () => {
  function Editable({ outcome }: { outcome: "success" | "error" }) {
    const [status, setStatus] = useState<FeedbackStatus>("idle");
    const [value, setValue] = useState("Reception");
    return (
      <InlineEdit
        label="Agent name"
        value={value}
        status={status}
        onSave={(next) => {
          setStatus("pending");
          window.setTimeout(() => {
            if (outcome === "success") setValue(next);
            setStatus(outcome);
          }, 10);
        }}
      />
    );
  }

  it("closes on success and shows Saved", async () => {
    render(<Editable outcome="success" />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Agent name: Reception" }));
    const box = screen.getByRole("textbox", { name: "Agent name" });
    fireEvent.change(box, { target: { value: "Front desk" } });
    fireEvent.submit(box.closest("form") as HTMLFormElement);
    await screen.findByRole("button", { name: "Edit Agent name: Front desk" });
    expect(screen.getByText("Saved")).toBeTruthy();
  });

  it("stays open with the text and the reason on failure", async () => {
    render(<Editable outcome="error" />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Agent name: Reception" }));
    const box = screen.getByRole("textbox", { name: "Agent name" }) as HTMLInputElement;
    fireEvent.change(box, { target: { value: "Front desk" } });
    fireEvent.submit(box.closest("form") as HTMLFormElement);
    expect((await screen.findByRole("alert")).textContent).toContain("did not save");
    expect(box.value).toBe("Front desk");
  });

  it("sends nothing when the text did not change, and Escape cancels", () => {
    const onSave = vi.fn();
    render(<InlineEdit label="Agent name" value="Reception" onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Agent name: Reception" }));
    const box = screen.getByRole("textbox", { name: "Agent name" });
    fireEvent.submit(box.closest("form") as HTMLFormElement);
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Edit Agent name: Reception" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Agent name" }), { key: "Escape" });
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
