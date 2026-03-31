import { describe, it, expect } from "vitest";
import { cn } from "@/lib/utils";

describe("cn (class name utility)", () => {
  it("returns a single class unchanged", () => {
    expect(cn("px-2")).toBe("px-2");
  });

  it("merges multiple classes", () => {
    expect(cn("px-2", "py-4")).toBe("px-2 py-4");
  });

  it("handles conditional classes", () => {
    const isActive = true;
    const isDisabled = false;
    expect(cn("base", isActive && "active", isDisabled && "disabled")).toBe("base active");
  });

  it("handles false/null/undefined values", () => {
    expect(cn("base", false, null, undefined, "end")).toBe("base end");
  });

  it("resolves Tailwind merge conflicts (last wins)", () => {
    // tailwind-merge: later class overrides conflicting earlier class
    expect(cn("px-2", "px-4")).toBe("px-4");
  });

  it("resolves padding conflicts", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("resolves text size conflicts", () => {
    expect(cn("text-sm", "text-lg")).toBe("text-lg");
  });

  it("resolves text color conflicts", () => {
    expect(cn("text-red-500", "text-blue-500")).toBe("text-blue-500");
  });

  it("resolves background color conflicts", () => {
    expect(cn("bg-red-500", "bg-blue-500")).toBe("bg-blue-500");
  });

  it("keeps non-conflicting classes together", () => {
    const result = cn("px-2", "py-4", "font-bold", "text-sm");
    expect(result).toContain("px-2");
    expect(result).toContain("py-4");
    expect(result).toContain("font-bold");
    expect(result).toContain("text-sm");
  });

  it("handles empty string", () => {
    expect(cn("")).toBe("");
  });

  it("handles no arguments", () => {
    expect(cn()).toBe("");
  });

  it("handles array input via clsx", () => {
    expect(cn(["px-2", "py-4"])).toBe("px-2 py-4");
  });

  it("handles object input via clsx", () => {
    expect(cn({ "px-2": true, "py-4": true, "hidden": false })).toBe("px-2 py-4");
  });

  it("resolves complex Tailwind conflicts", () => {
    // margin overrides
    expect(cn("mt-2", "mt-4")).toBe("mt-4");
    // border-radius overrides
    expect(cn("rounded-sm", "rounded-lg")).toBe("rounded-lg");
  });

  it("preserves arbitrary values", () => {
    expect(cn("text-[10px]", "mt-2")).toBe("text-[10px] mt-2");
  });

  it("handles mixed conditional and regular classes", () => {
    const variant = "primary" as string;
    expect(
      cn("base", variant === "primary" && "bg-blue-500", variant === "secondary" && "bg-gray-500")
    ).toBe("base bg-blue-500");
  });
});
