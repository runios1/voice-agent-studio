import { describe, expect, it } from "vitest";
import { getPath, isMeaningful, setPath } from "./paths";

describe("getPath", () => {
  const tree = { a: { b: { c: 1 }, list: [1, 2] } };
  it("reads nested values", () => {
    expect(getPath(tree, "a.b.c")).toBe(1);
    expect(getPath(tree, "a.list")).toEqual([1, 2]);
  });
  it("returns undefined for missing paths", () => {
    expect(getPath(tree, "a.x.y")).toBeUndefined();
    expect(getPath(tree, "a.b.c.d")).toBeUndefined();
  });
});

describe("setPath (immutable)", () => {
  it("sets a nested value without mutating the source", () => {
    const src = { a: { b: { c: 1 }, keep: 9 } };
    const out = setPath(src, "a.b.c", 2);
    expect(out.a.b.c).toBe(2);
    expect(src.a.b.c).toBe(1); // source untouched
    expect(out.a.keep).toBe(9); // siblings preserved
    expect(out).not.toBe(src);
    expect(out.a).not.toBe(src.a);
  });
  it("creates intermediate objects when absent", () => {
    const out = setPath({} as Record<string, unknown>, "x.y.z", 5);
    expect(getPath(out, "x.y.z")).toBe(5);
  });
});

describe("isMeaningful", () => {
  it("treats null/empty as not meaningful", () => {
    expect(isMeaningful(null)).toBe(false);
    expect(isMeaningful("")).toBe(false);
    expect(isMeaningful("   ")).toBe(false);
    expect(isMeaningful([])).toBe(false);
    expect(isMeaningful({})).toBe(false);
  });
  it("treats real content as meaningful", () => {
    expect(isMeaningful("hi")).toBe(true);
    expect(isMeaningful([1])).toBe(true);
    expect(isMeaningful(false)).toBe(true); // an explicit boolean counts
    expect(isMeaningful(0)).toBe(true);
  });
});
