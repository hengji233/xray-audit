import { describe, expect, it } from "vitest"
import worker from "../src/index"

describe("gateway protocol", () => {
  it("serves an unauthenticated health response", async () => {
    const r = await worker.fetch(new Request("https://example.test/health"), {} as never)
    expect(r.status).toBe(200)
    expect(await r.json()).toMatchObject({ ok: true, data: { status: "ok" } })
  })
  it("rejects storage requests without the bearer token", async () => {
    const r = await worker.fetch(new Request("https://example.test/v1/storage/query_events", { method: "POST", body: "{}" }), { GATEWAY_TOKEN: "s".repeat(32) } as never)
    expect(r.status).toBe(401)
    expect(await r.json()).toMatchObject({ ok: false, error: { code: "UNAUTHORIZED", retryable: false } })
  })
  it("does not expose arbitrary SQL", async () => {
    const db = {} as D1Database
    const token = "s".repeat(32)
    const r = await worker.fetch(new Request("https://example.test/v1/storage/sql", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: "{}" }), { DB: db, GATEWAY_TOKEN: token } as never)
    expect(r.status).toBe(500)
    expect(await r.json()).toMatchObject({ ok: false, error: { code: "UNKNOWN_OPERATION" } })
  })
  it("fails closed when the gateway secret is missing", async () => {
    const r = await worker.fetch(new Request("https://example.test/v1/storage/query_events", { method: "POST", headers: { Authorization: "Bearer undefined" }, body: "{}" }), { DB: {} as D1Database } as never)
    expect(r.status).toBe(500)
    expect(await r.json()).toMatchObject({ ok: false, error: { code: "CONFIGURATION_ERROR" } })
  })
})
