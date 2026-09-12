import { Skeleton } from "@/components/ui/skeleton";

// ARCHITECTURE.md §5: "Every list route ships four states: loading skeleton,
// empty, error, populated. This is a review gate, not a suggestion."
export function ListLoadingState({ rows = 5 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="surface space-y-2 p-3">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}
