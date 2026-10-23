"use client";

/**
 * A ROW OF FILTER CHIPS over one list: one chip on at a time (`single`), or any number
 * (`multiple`). Each chip is `ui.tsx`'s `FilterChip`, which stays the one chip primitive
 * (its look is already on twenty-odd screens); this adds what each of those screens was
 * doing by hand around it: the group name, the selection rule, an optional "All" chip and
 * wrapping at phone width. Ideas from uiarc's `chip-group` (MIT, see ./LICENSE); its
 * check-mark morph and per-chip colour are not carried over.
 *
 * Chips toggle a filter over what is on screen. To CHOOSE a value in a form, use
 * `RadioGroup` (one) or `MultiSelect` / checkboxes (several).
 */

import { FilterChip } from "@/components/ui";

export type Chip = { value: string; label: string };

type Common = {
  /** The group's accessible name: "Filter calls by outcome". */
  label: string;
  chips: Chip[];
  className?: string;
};

export type ChipGroupProps =
  | (Common & {
      mode: "single";
      value: string | null;
      onChange: (value: string | null) => void;
      /** Adds a leading chip that clears the filter ("All"). */
      allLabel?: string;
    })
  | (Common & {
      mode: "multiple";
      value: string[];
      onChange: (value: string[]) => void;
      allLabel?: string;
    });

export function ChipGroup(props: ChipGroupProps) {
  const { label, chips, className = "" } = props;
  const isOn = (value: string) =>
    props.mode === "single" ? props.value === value : props.value.includes(value);
  const nothingOn = props.mode === "single" ? props.value === null : props.value.length === 0;

  const toggle = (value: string) => {
    if (props.mode === "single") {
      props.onChange(props.value === value ? null : value);
    } else {
      const next = isOn(value) ? props.value.filter((v) => v !== value) : [...props.value, value];
      // The caller's chip order, not the order things were pressed in.
      props.onChange(chips.map((c) => c.value).filter((v) => next.includes(v)));
    }
  };
  const clear = () => (props.mode === "single" ? props.onChange(null) : props.onChange([]));

  return (
    <div role="group" aria-label={label} className={`flex flex-wrap gap-2 ${className}`}>
      {props.allLabel ? <FilterChip label={props.allLabel} active={nothingOn} onClick={clear} /> : null}
      {chips.map((chip) => (
        <FilterChip key={chip.value} label={chip.label} active={isOn(chip.value)} onClick={() => toggle(chip.value)} />
      ))}
    </div>
  );
}
