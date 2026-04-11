import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";

import { CollapsibleStrip } from "@/components/ui/collapsible-strip";

/**
 * Node 22+ ships a built-in `localStorage` stub when launched with
 * `--localstorage-file` (which vitest's worker spawn happens to trigger
 * without a backing path). That stub masks jsdom's full Storage implementation
 * and leaves `window.localStorage` as a bare empty object with no methods.
 *
 * These tests install a tiny in-memory Storage shim via `vi.stubGlobal` so
 * CollapsibleStrip's getItem/setItem calls exercise their real branches.
 */
const STORAGE_PREFIX = "nuri-dash-strip:";

function makeStorage(initial: Record<string, string> = {}): Storage {
  const store = new Map<string, string>(Object.entries(initial));
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
}

describe("CollapsibleStrip", () => {
  let storage: Storage;

  beforeEach(() => {
    storage = makeStorage();
    vi.stubGlobal("localStorage", storage);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns null when count=0 and no emptyText", () => {
    const { container } = render(
      <CollapsibleStrip id="zero" title="알림" icon="⚠" count={0}>
        <div>hidden</div>
      </CollapsibleStrip>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders empty hint when count=0 and emptyText is provided", () => {
    render(
      <CollapsibleStrip id="empty-hint" title="알림" icon="⚠" count={0} emptyText="위험 요소 없음">
        <div>hidden</div>
      </CollapsibleStrip>,
    );
    const hint = screen.getByTestId("strip-empty-empty-hint");
    expect(hint).toBeInTheDocument();
    expect(hint.textContent).toContain("위험 요소 없음");
    expect(hint.textContent).toContain("⚠");
  });

  it("renders children expanded by default and shows X close button", () => {
    render(
      <CollapsibleStrip id="default" title="알림" icon="⚠" count={3}>
        <div>body content</div>
      </CollapsibleStrip>,
    );
    expect(screen.getByTestId("strip-default")).toBeInTheDocument();
    expect(screen.getByText("body content")).toBeInTheDocument();
    expect(screen.getByTestId("strip-close-default")).toBeInTheDocument();
    expect(screen.queryByTestId("strip-collapsed-default")).not.toBeInTheDocument();
  });

  it("collapses to a 1-line button when close is clicked and persists via localStorage", () => {
    render(
      <CollapsibleStrip id="toggle-a" title="알림" icon="⚠" count={2}>
        <div>body content</div>
      </CollapsibleStrip>,
    );
    fireEvent.click(screen.getByTestId("strip-close-toggle-a"));

    const collapsed = screen.getByTestId("strip-collapsed-toggle-a");
    expect(collapsed).toBeInTheDocument();
    expect(collapsed.textContent).toContain("알림");
    expect(collapsed.textContent).toContain("(2)");
    expect(screen.queryByTestId("strip-toggle-a")).not.toBeInTheDocument();
    expect(storage.getItem(STORAGE_PREFIX + "toggle-a")).toBe("true");
  });

  it("expands back from the collapsed button and clears the persisted flag", () => {
    storage = makeStorage({ [STORAGE_PREFIX + "toggle-b"]: "true" });
    vi.stubGlobal("localStorage", storage);

    render(
      <CollapsibleStrip id="toggle-b" title="알림" icon="⚠" count={5}>
        <div>body content</div>
      </CollapsibleStrip>,
    );
    const collapsed = screen.getByTestId("strip-collapsed-toggle-b");
    fireEvent.click(collapsed);

    expect(screen.getByTestId("strip-toggle-b")).toBeInTheDocument();
    expect(screen.getByText("body content")).toBeInTheDocument();
    expect(storage.getItem(STORAGE_PREFIX + "toggle-b")).toBe("false");
  });

  it("swallows localStorage.getItem exceptions during hydration", () => {
    const throwingStorage: Storage = {
      ...storage,
      getItem() {
        throw new Error("quota");
      },
    };
    vi.stubGlobal("localStorage", throwingStorage);

    expect(() => {
      render(
        <CollapsibleStrip id="hydrate-fail" title="알림" icon="⚠" count={1}>
          <div>body content</div>
        </CollapsibleStrip>,
      );
    }).not.toThrow();
    // Without persistence the default (expanded) still renders
    expect(screen.getByText("body content")).toBeInTheDocument();
  });

  it("swallows localStorage.setItem exceptions during toggle", () => {
    const throwingStorage: Storage = {
      ...storage,
      setItem() {
        throw new Error("quota");
      },
    };
    vi.stubGlobal("localStorage", throwingStorage);

    render(
      <CollapsibleStrip id="set-fail" title="알림" icon="⚠" count={1}>
        <div>body content</div>
      </CollapsibleStrip>,
    );
    expect(() => {
      act(() => {
        fireEvent.click(screen.getByTestId("strip-close-set-fail"));
      });
    }).not.toThrow();
    expect(screen.getByTestId("strip-collapsed-set-fail")).toBeInTheDocument();
  });
});
