import { describe, expect, test } from "vitest";
import { resolveApiUrl } from "@/lib/api";

describe("resolveApiUrl", () => {
  test("uses the production backend when Vercel has no API URL", () => {
    expect(resolveApiUrl("production")).toBe("https://vasool-ta24.onrender.com");
  });

  test("refuses localhost as a production backend URL", () => {
    expect(resolveApiUrl("production", "http://127.0.0.1:8000/")).toBe("https://vasool-ta24.onrender.com");
    expect(resolveApiUrl("production", "http://localhost:8000")).toBe("https://vasool-ta24.onrender.com");
  });

  test("keeps the local backend as the development default", () => {
    expect(resolveApiUrl("development")).toBe("http://127.0.0.1:8000");
  });
});
