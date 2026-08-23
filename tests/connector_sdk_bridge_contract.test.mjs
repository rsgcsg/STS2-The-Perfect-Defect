import assert from "node:assert/strict";
import test from "node:test";

import {
  canonicalizeReadResponses,
  includeReadForPolicy
} from "../tools/connector_sdk_bridge_contract.mjs";

function surfaceCard(readId, targetReferentId) {
  return {
    read_id: readId,
    kind: "surface_card",
    target_referent_id: targetReferentId,
    completeness: { status: "complete" }
  };
}

test("duplicate surface_card kinds retain both independently targeted Reads", () => {
  const second = surfaceCard("read:surface_card:card-2", "card-2");
  const first = surfaceCard("read:surface_card:card-1", "card-1");

  const canonical = canonicalizeReadResponses([second, first]);

  assert.equal(canonical.length, 2);
  assert.deepEqual(canonical.map((read) => read.read_id), [
    "read:surface_card:card-1",
    "read:surface_card:card-2"
  ]);
  assert.deepEqual(canonical.map((read) => read.target_referent_id), ["card-1", "card-2"]);
});

test("duplicate Read input order cannot change canonical bridge output", () => {
  const first = surfaceCard("read:surface_card:card-1", "card-1");
  const second = surfaceCard("read:surface_card:card-2", "card-2");
  assert.deepEqual(
    canonicalizeReadResponses([first, second]),
    canonicalizeReadResponses([second, first])
  );
});

test("none policy prefetches no advertised Reads without changing their descriptors", () => {
  const descriptors = [
    surfaceCard("read:surface_card:card-1", "card-1"),
    surfaceCard("read:surface_card:card-2", "card-2")
  ];
  const include = includeReadForPolicy({ mode: "none" });
  assert.deepEqual(descriptors.filter(include), []);
  assert.equal(descriptors.length, 2);
});

test("duplicate opaque read_id fails closed instead of overwriting", () => {
  const first = surfaceCard("read:surface_card:same", "card-1");
  const second = surfaceCard("read:surface_card:same", "card-2");
  assert.throws(
    () => canonicalizeReadResponses([first, second]),
    /duplicate Connector Read identity/u
  );
});
