import { Button } from "@/components/ui/button";

export function ListErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex min-h-52 flex-col items-center justify-center gap-3 rounded border border-destructive/30 bg-destructive/5 px-6 py-12 text-center shadow-[inset_3px_0_0_hsl(var(--destructive))]"
    >
      <p className="text-sm font-medium text-destructive">{message}</p>
      {onRetry ? (
        <Button variant="outline" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
