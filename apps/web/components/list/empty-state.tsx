export function ListEmptyState({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="surface flex min-h-52 flex-col items-center justify-center gap-2 border-dashed px-6 py-12 text-center">
      <span
        className="mb-2 grid h-9 w-9 place-items-center rounded-full border border-border bg-muted text-lg text-muted-foreground"
        aria-hidden="true"
      >
        +
      </span>
      <p className="font-semibold text-foreground">{title}</p>
      {description ? (
        <p className="text-sm text-muted-foreground">{description}</p>
      ) : null}
    </div>
  );
}
