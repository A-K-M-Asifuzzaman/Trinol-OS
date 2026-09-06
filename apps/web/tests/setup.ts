import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";

// Node 22+ ships a native, stable globalThis.localStorage that throws a
// SecurityError unless the process is started with --localstorage-file —
// msw's Node-side cookie jar (used by setupServer to track cookies across
// intercepted requests) reads that global directly. jsdom's own
// window.localStorage is unaffected; this only patches the Node-global one
// msw actually touches, with a throwaway in-memory Storage so its cookie
// jar has somewhere to write. CI targets Node 22 in Docker either way — this
// is a test-environment shim, not a product concern.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) ?? null) : null;
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
}
Object.defineProperty(globalThis, "localStorage", {
  value: new MemoryStorage(),
  configurable: true,
  writable: true,
});

const { server } = await import("./msw/server");

// TESTING.md's own rule for every external dependency, applied here: no
// test may reach a real network endpoint. An unhandled request is a bug in
// the test (a missing handler), not something to silently pass through.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
