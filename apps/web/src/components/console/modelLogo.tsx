import { modelMaker, modelMonogram } from "@/lib/modelLogos";

/**
 * A LANGUAGE MODEL'S MAKER, as a small square tile before the model's name. Admin console
 * only (D-679). The tile is white with a hairline in both themes, so a single-colour mark
 * (OpenAI's is drawn in `currentColor`, which an `<img>` resolves to black) stays legible in
 * dark mode without recolouring anybody's logo. An unknown maker is a monogram, not a guess.
 *
 * Decorative: the model's name is printed beside it and the maker's name is in `title`.
 */
export function ModelLogo({ label, modelId }: { label: string; modelId?: string | null }) {
  const maker = modelMaker(modelId, label);
  return (
    <span
      aria-hidden
      title={maker?.name}
      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-line bg-white"
      data-model-maker={maker?.name ?? "unknown"}
    >
      {maker ? (
        // eslint-disable-next-line @next/next/no-img-element -- a 16px static brand file; next/image adds nothing here
        <img src={maker.src} alt="" width={16} height={16} className="h-4 w-4 object-contain" />
      ) : (
        <span className="text-[11px] font-semibold leading-none text-slate-600">
          {modelMonogram(label)}
        </span>
      )}
    </span>
  );
}
