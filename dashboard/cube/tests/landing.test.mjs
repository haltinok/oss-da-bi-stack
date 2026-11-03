// Where a sign-in sends the browser back (dashboard/cube/cube-client.mjs): `node --test dashboard/cube/tests/landing.test.mjs`
import assert from "node:assert/strict";
import { test } from "node:test";
import { loginRedirect } from "../cube-client.mjs";

test("a sign-in that began at the site root lands on the start page, for everybody", () => {
  assert.equal(loginRedirect("/", "https://demo.example", "https://demo.example/"), "https://demo.example/home/");
});

test("a sign-in that began anywhere else comes back to that page", () => {
  assert.equal(loginRedirect("/d/sales-overview", "https://demo.example", "https://demo.example/d/sales-overview"), "https://demo.example/d/sales-overview");
  assert.equal(loginRedirect("/admin/", "https://demo.example", "https://demo.example/admin/"), "https://demo.example/admin/");
  assert.equal(loginRedirect("/home/", "https://demo.example", "https://demo.example/home/"), "https://demo.example/home/");
});
