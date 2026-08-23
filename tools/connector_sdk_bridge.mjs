#!/usr/bin/env node
/** Strict NDJSON bridge to the exact sibling Connector TypeScript SDK. */

import readline from "node:readline";
import process from "node:process";
import { pathToFileURL } from "node:url";

function option(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 && index + 1 < process.argv.length ? process.argv[index + 1] : fallback;
}

const sdkPath = option("--sdk");
const endpoint = option("--endpoint", "http://127.0.0.1:15526");
const timeoutMs = Number(option("--timeout-ms", "5000"));
if (!sdkPath || !Number.isInteger(timeoutMs) || timeoutMs <= 0) {
  throw new Error("usage: connector_sdk_bridge.mjs --sdk <dist/index.js> [--endpoint URL]");
}

const {
  EnvironmentControllerSession,
  PlayerEnvironmentRestClient,
  prefetchPlayerEnvironmentDecisionBundle
} = await import(pathToFileURL(sdkPath).href);

const client = new PlayerEnvironmentRestClient(endpoint, timeoutMs);
let capabilities = null;
let controller = null;

function ensureBoundRuntime(runtimeInstanceId, environmentFingerprint = null) {
  if (!capabilities) throw new Error("bridge is not connected");
  if (runtimeInstanceId !== capabilities.host.runtime_instance_id) {
    throw new Error("Player Environment runtime identity changed");
  }
  if (environmentFingerprint != null
      && environmentFingerprint !== capabilities.environment_fingerprint) {
    throw new Error("Player Environment fingerprint changed");
  }
}

async function connect() {
  const decoded = await client.capabilities();
  if (capabilities
      && decoded.data.host.runtime_instance_id !== capabilities.host.runtime_instance_id) {
    throw new Error("Player Environment runtime identity changed");
  }
  capabilities = decoded.data;
  return capabilities;
}

async function observeBundle() {
  if (!capabilities) await connect();
  const observation = (await client.observe()).data;
  ensureBoundRuntime(
    observation.session.runtime_instance_id,
    observation.session.environment_fingerprint
  );
  const bundle = await prefetchPlayerEnvironmentDecisionBundle(
    observation,
    async (readId, expectedSnapshotId) => (await client.read(readId, expectedSnapshotId)).data
  );
  const reads = {};
  for (const read of bundle.reads) {
    if (Object.hasOwn(reads, read.kind)) {
      throw new Error(`duplicate advertised Read kind is unsupported: ${read.kind}`);
    }
    reads[read.kind] = read;
  }
  return { snapshot: bundle.observation, reads };
}

async function acquire() {
  if (!capabilities) await connect();
  if (!controller) {
    controller = new EnvironmentControllerSession(client, {
      productId: "stpd-live-s1",
      productName: "STPD Experimental Live S1",
      productVersion: "1.0.0"
    });
    await controller.register(capabilities.host, capabilities.control);
  }
  await controller.credentials();
  return controller.snapshot();
}

async function release() {
  if (controller) await controller.close();
  controller = null;
  return { released: true };
}

async function submit(input) {
  if (!controller) throw new Error("controller is not acquired");
  const credentials = await controller.credentials();
  const receipt = (await client.submit({
    requestId: String(input.request_id),
    expectedSnapshotId: String(input.expected_snapshot_id),
    boundActionId: String(input.bound_action_id),
    ...credentials
  })).data;
  return { receipt, controller: controller.snapshot() };
}

async function dispatch(message) {
  switch (message.op) {
    case "ping": return { endpoint, sdk_path: sdkPath };
    case "connect": return connect();
    case "observe_bundle": return observeBundle();
    case "acquire": return acquire();
    case "release": return release();
    case "submit": return submit(message);
    case "close": await release(); return { closed: true };
    default: throw new Error(`unsupported bridge operation: ${message.op}`);
  }
}

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  let message;
  try {
    message = JSON.parse(line);
    const result = await dispatch(message);
    process.stdout.write(`${JSON.stringify({ id: message.id, ok: true, result })}\n`);
    if (message.op === "close") break;
  } catch (error) {
    process.stdout.write(`${JSON.stringify({
      id: message?.id ?? null,
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    })}\n`);
  }
}

await release();
