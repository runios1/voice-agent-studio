import { describe, expect, it } from "vitest";
import { normalizePhone, parseLeadsCsv } from "./leadImport";

describe("normalizePhone", () => {
  it("accepts plain and formatted numbers", () => {
    expect(normalizePhone("+1 (555) 000-1234")).toBe("+15550001234");
    expect(normalizePhone("5550001234")).toBe("5550001234");
  });

  it("rejects too-short, too-long, and non-numeric input", () => {
    expect(normalizePhone("12345")).toBeNull();
    expect(normalizePhone("1".repeat(20))).toBeNull();
    expect(normalizePhone("call me maybe")).toBeNull();
    expect(normalizePhone("")).toBeNull();
  });
});

describe("parseLeadsCsv", () => {
  it("parses phone + name rows", () => {
    const { valid, invalid } = parseLeadsCsv(
      "+15550001111,Ada Lovelace\n+15550002222,Grace Hopper",
    );
    expect(invalid).toEqual([]);
    expect(valid).toEqual([
      { phone: "+15550001111", display_name: "Ada Lovelace" },
      { phone: "+15550002222", display_name: "Grace Hopper" },
    ]);
  });

  it("skips a header row", () => {
    const { valid } = parseLeadsCsv("phone,name\n+15550001111,Ada");
    expect(valid).toEqual([{ phone: "+15550001111", display_name: "Ada" }]);
  });

  it("allows a bare phone with no name", () => {
    const { valid } = parseLeadsCsv("+15550001111");
    expect(valid).toEqual([{ phone: "+15550001111", display_name: undefined }]);
  });

  it("flags invalid phone numbers with a reason, without dropping the batch", () => {
    const { valid, invalid } = parseLeadsCsv("not-a-phone,Someone\n+15550001111,Ada");
    expect(valid).toEqual([{ phone: "+15550001111", display_name: "Ada" }]);
    expect(invalid).toEqual([{ raw: "not-a-phone,Someone", reason: "not a valid phone number" }]);
  });

  it("flags duplicates within the batch and against existing leads", () => {
    const { valid, invalid } = parseLeadsCsv(
      "+15550001111,Ada\n+15550001111,Ada again",
      [{ phone: "+15550002222", display_name: "Already added" }],
    );
    expect(valid).toEqual([{ phone: "+15550001111", display_name: "Ada" }]);
    expect(invalid).toEqual([
      { raw: "+15550001111,Ada again", reason: "duplicate phone number" },
    ]);
  });

  it("ignores blank lines", () => {
    const { valid, invalid } = parseLeadsCsv("+15550001111,Ada\n\n\n+15550002222,Grace");
    expect(valid).toHaveLength(2);
    expect(invalid).toEqual([]);
  });
});
