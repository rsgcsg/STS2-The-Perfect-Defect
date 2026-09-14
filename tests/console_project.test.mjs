import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

class Element {
  constructor(tag) {
    this.tag = tag;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
  }
  append(...items) {
    this.children.push(...items);
  }
  replaceChildren(...items) {
    this.children = items;
  }
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
}
const walk = (node) => [node, ...(node?.children || []).flatMap(walk)];
const text = (node) =>
  walk(node)
    .map((item) => item.textContent || "")
    .join("\n");
const find = (node, predicate) => {
  const result = walk(node).find(predicate);
  assert.ok(result, "expected element");
  return result;
};
const action = (node, name) =>
  find(node, (element) => element.dataset?.action === name);
const field = (node, name) => find(node, (element) => element.name === name);
const id = (digit) => digit.repeat(64);
const uploadId = "a".repeat(32);
const enrollmentId = "e".repeat(32);
const memberId = "f".repeat(32);
const owner = (role = "member", subject = "person") => ({
  status: "signed_in",
  csrf_token: "local-csrf",
  device_id: "this-pc",
  principal: { role, subject, email: subject + "@example.test" },
  devices: [
    {
      device_id: "this-pc",
      name: "This computer",
      ownership: "owned_by_you",
      active: true,
    },
    {
      device_id: "other-pc",
      name: "Other computer",
      ownership: "owned_by_you",
      active: true,
    },
    {
      device_id: "shared-pc",
      name: "Teammate",
      ownership: "shared",
      active: true,
    },
    {
      device_id: "revoked-pc",
      name: "Revoked",
      ownership: "owned_by_you",
      active: false,
    },
  ],
});
const emptyList = () => ({
  items: [],
  templates: [],
  total: 0,
  next_offset: null,
  availability: "available",
});
function setup({
  mode = "local",
  identity = owner(),
  view = "statistics",
  handler = () => emptyList(),
  query = "",
} = {}) {
  const calls = [],
    notice = new Element("div"),
    confirms = [];
  let selectedScope = mode === "local" ? "local" : "project",
    generation = 0,
    reloads = 0;
  const context = vm.createContext({
    document: {
      body: { dataset: { mode, cloudUrl: "https://hub.example.test" } },
      getElementById: () => notice,
      createElement: (tag) => new Element(tag),
    },
    location: { search: "?view=" + view + query },
    URL,
    URLSearchParams,
    Date,
    AbortSignal,
    window: {
      confirm: (message) => {
        confirms.push(message);
        return true;
      },
      SpireIdentity: {
        context: () =>
          `${selectedScope}:${identity?.principal?.subject || "anonymous"}:${generation}`,
        isLocal: () => mode === "local" && selectedScope === "local",
        api: (route, query) => {
          const params = new URLSearchParams(query);
          if (!["project", "local"].includes(selectedScope))
            params.set("device", selectedScope);
          return (
            (mode === "local" ? "/api/project/" : "/app/api/") +
            route +
            (params.size ? "?" + params : "")
          );
        },
      },
    },
    fetch: async (url, options) => {
      calls.push({ url, options });
      const body = await handler(url, options);
      return {
        ok: !(body?.httpStatus >= 400),
        status: body?.httpStatus || 200,
        json: async () => body,
      };
    },
  });
  vm.runInContext(
    readFileSync(
      new URL("../stpd/console/project.js", import.meta.url),
      "utf8",
    ),
    context,
  );
  const ui = context.window.SpireProject;
  ui.reload = async () => {
    reloads++;
  };
  return {
    ui,
    calls,
    notice,
    confirms,
    context,
    get reloads() {
      return reloads;
    },
    render: () => ui.render(view, identity),
    scope: (value) => {
      selectedScope = value;
      generation++;
    },
    account: (value) => {
      identity = value;
      generation++;
    },
    navigate: (newView, newQuery = "") => {
      view = newView;
      context.location.search = "?view=" + view + newQuery;
    },
  };
}
const post = (calls) => calls.filter((call) => call.options.method === "POST");
const body = (call) => JSON.parse(call.options.body);
const template = {
  template_id: id("b"),
  template: {
    schema: "stpd/collection-activity-v1",
    name: "Bounded capture",
    description: "New recordings only",
    consent_text: "Reviewed consent",
    activity_id: "canary",
    version: 1,
    game: { version: "exact-game" },
  },
};
const enrollment = {
  schema: "stpd/collection-enrollment-v1",
  template_id: id("b"),
  template: template.template,
  enrollment_id: enrollmentId,
  device_id: "this-pc",
  campaign_id: "campaign-" + enrollmentId,
  declared_at: 1700000000,
};
const exportManifest = {
  schema: "stpd/project-export-v1",
  export_id: id("c"),
  created_at: "2026-09-14T00:00:00Z",
  files_count: 1,
  total_bytes: 42,
  files: [
    {
      file_id: id("d"),
      sha256: id("e"),
      size: 42,
      filename: id("d") + ".bin",
      type: "payload",
      role: "dataset",
      upload_id: null,
    },
  ],
};

test("statistics consumes owner coverage and occurrence units without replacing unknowns with zero", async () => {
  const metric = { value: null, known: 1, unknown: 2, partial: true };
  const data = {
    schema: "stpd/project-statistics-v1",
    observed_at: "2026-09-14T00:00:00Z",
    uploads: 3,
    unique_content_ids: 2,
    duplicate_content_uploads: 1,
    metrics: {
      canonical: metric,
      real_failures: { value: 0, known: 3, unknown: 0, partial: false },
      native_starts: { value: 1, known: 1, unknown: 2, partial: true },
    },
    facets: {
      device: {
        availability: "available",
        known: 3,
        unknown: 0,
        items: [{ value: "this-pc", count: 3 }],
        truncated: false,
      },
    },
    collection_profiles: {
      availability: "partial",
      sources: 3,
      profiles_available: 1,
      profiles_missing: 2,
      records: 4,
      partial: true,
      facets: {
        game_version: {
          availability: "unavailable",
          known: 0,
          unknown: 4,
          items: [],
        },
      },
    },
    artifacts: { counts: { dataset: 2 }, inventory_complete: null },
  };
  const env = setup({
      handler: (url) => {
        assert.equal(url, "/api/project/statistics");
        return data;
      },
    }),
    page = await env.render();
  assert.equal(page.dataset.observedAt, data.observed_at);
  assert.match(text(page), /部分汇总/);
  assert.match(text(page), /未知 2 份/);
  assert.match(text(page), /不能单独证明 uninterrupted Full Run/);
  assert.match(text(page), /不是云存储桶的完整盘点/);
  assert.match(text(page), /记录出现次数/);
  const cards = walk(page).filter((node) =>
    node.className?.includes("metric-value"),
  );
  assert.equal(cards[2].textContent, "未知");
  assert.equal(cards[3].textContent, "0");
});

test("project catalog preserves the selected device filter but never calls nonexistent local catalog", async () => {
  const env = setup({ view: "research" });
  env.scope("other-pc");
  await env.render();
  assert.equal(env.calls.length, 3);
  assert.ok(env.calls.every((call) => call.url.includes("device=other-pc")));
  env.scope("local");
  env.calls.length = 0;
  await env.render();
  assert.ok(env.calls.every((call) => call.url.startsWith("/api/project/")));
});

test("member and personal admin views never request browser management endpoints", async () => {
  for (const [mode, role] of [
    ["local", "admin"],
    ["cloud", "member"],
  ]) {
    const env = setup({ mode, identity: owner(role), view: "members" }),
      page = await env.render();
    assert.equal(env.calls.length, 0);
    assert.match(
      text(page),
      role === "admin" ? /云端浏览器/ : /当前是项目成员/,
    );
  }
});

test("browser admin invitation uses explicit role quota and csrf; promotions and disables confirm", async () => {
  const item = {
    member_id: memberId,
    email: "member@example.test",
    role: "member",
    status: "active",
    device_quota: 3,
    enroll_devices: true,
    active_device_count: 1,
    owned_device_count: 2,
  };
  const env = setup({
    mode: "cloud",
    identity: owner("admin"),
    view: "members",
    handler: (url, options) =>
      options.method === "POST" ? {} : { items: [item], total: 1 },
  });
  let page = await env.render();
  field(page, "email").value = "new@example.test";
  await action(page, "member-save-invite").onclick();
  assert.deepEqual(body(post(env.calls)[0]), {
    email: "new@example.test",
    role: "member",
    device_quota: 3,
    enroll_devices: true,
    csrf_token: "local-csrf",
  });
  page = await env.render();
  const row = find(
    page,
    (node) =>
      node.tag === "section" &&
      node.children[0]?.textContent === "member@example.test",
  );
  field(row, "role").value = "admin";
  await action(row, "member-save-" + memberId).onclick();
  assert.equal(env.confirms.length, 1);
  assert.equal(body(post(env.calls)[1]).role, "admin");
  await action(row, "member-status-" + memberId).onclick();
  assert.equal(body(post(env.calls)[2]).status, "disabled");
  assert.equal(env.confirms.length, 2);
});

test("server last-admin rejection remains a visible failure without optimistic success", async () => {
  const env = setup({
    mode: "cloud",
    identity: owner("admin"),
    view: "members",
    handler: (url, options) =>
      options.method === "POST"
        ? { httpStatus: 409, error: "last_admin_required" }
        : {
            items: [
              {
                member_id: memberId,
                email: "a@example.test",
                role: "admin",
                status: "active",
                device_quota: 3,
                enroll_devices: true,
              },
            ],
            total: 1,
          },
  });
  const page = await env.render();
  await action(page, "member-status-" + memberId).onclick();
  assert.match(text(env.notice), /保留至少一位/);
  assert.equal(env.reloads, 0);
});

function campaignHandler(url, options) {
  if (url.includes("/enrollments?")) return emptyList();
  if (url.endsWith("/enroll")) return enrollment;
  if (url.endsWith("/prepare"))
    return {
      schema: "stpd/local-campaign-preparation-v1",
      status: "native_binding_required",
      native_binding_verified: false,
      delivery_started: false,
    };
  return { templates: [template], total: 1 };
}
test("campaign enrollment requires three deliberate declarations and uses only the local owned active device", async () => {
  const env = setup({ view: "campaigns", handler: campaignHandler });
  let page = await env.render();
  const device = field(page, "device_id");
  assert.deepEqual(
    device.children.map((x) => x.value),
    ["this-pc"],
  );
  await action(page, "enroll-" + id("b")).onclick();
  assert.equal(post(env.calls).length, 0);
  assert.match(text(env.notice), /分别确认/);
  for (const name of [
    "human_origin_attested",
    "upload_authorized",
    "project_sharing_authorized",
  ]) {
    const input = field(page, name);
    assert.equal(input.checked, false);
    input.checked = true;
    input.onchange();
  }
  await action(page, "enroll-" + id("b")).onclick();
  assert.equal(
    post(env.calls)[0].url,
    "/api/member/campaigns/" + id("b") + "/enroll",
  );
  assert.deepEqual(body(post(env.calls)[0]), {
    device_id: "this-pc",
    consent: {
      human_origin_attested: true,
      upload_authorized: true,
      project_sharing_authorized: true,
    },
  });
  page = await env.render();
  await action(page, "prepare-" + enrollmentId).onclick();
  assert.equal(
    post(env.calls)[1].url,
    "/api/member/campaigns/" + enrollmentId + "/prepare",
  );
  assert.deepEqual(body(post(env.calls)[1]), {});
  page = await env.render();
  assert.match(text(page), /需要精确原生绑定/);
  assert.match(text(page), /尚未启动/);
  assert.match(text(page), /不是已验证的真人来源/);
});

test("persisted activity enrollment can prepare after a fresh page without reattesting consent", async () => {
  const env = setup({
    view: "campaigns",
    handler: (url, options) =>
      url.includes("/enrollments?")
        ? { items: [enrollment], total: 1 }
        : campaignHandler(url, options),
  });
  const page = await env.render();
  await action(page, "prepare-" + enrollmentId).onclick();
  assert.equal(post(env.calls).length, 1);
  assert.ok(post(env.calls)[0].url.endsWith("/prepare"));
});

test("mismatched enrollment response cannot become a local preparation target", async () => {
  const env = setup({
    view: "campaigns",
    handler: (url, options) =>
      url.endsWith("/enroll")
        ? { ...enrollment, device_id: "someone-else" }
        : campaignHandler(url, options),
  });
  let page = await env.render();
  for (const name of [
    "human_origin_attested",
    "upload_authorized",
    "project_sharing_authorized",
  ])
    field(page, name).checked = true;
  await action(page, "enroll-" + id("b")).onclick();
  page = await env.render();
  assert.match(text(env.notice), /enrollment_identity_mismatch/);
  assert.equal(
    walk(page).some((n) => n.dataset?.action === "prepare-" + enrollmentId),
    false,
  );
});

test("raw export selection is exact, csrf scoped, and creating a manifest does not claim completed download", async () => {
  const env = setup({
    view: "downloads",
    handler: (url, options) => {
      if (url.includes("/collections?"))
        return {
          items: [
            {
              id: uploadId,
              upload_id: uploadId,
              status: "verified",
              device_id: "this-pc",
            },
          ],
          total: 1,
        };
      if (options.method === "POST") return exportManifest;
      if (url.endsWith("/download-status"))
        return {
          status: "downloading",
          export_id: id("c"),
          verified_files: 1,
          verified_bytes: 42,
          total_files: 2,
          total_bytes: 84,
        };
      return exportManifest;
    },
  });
  let page = await env.render(),
    selected = field(page, "collection-" + uploadId);
  selected.checked = true;
  selected.onchange();
  await action(page, "create-export").onclick();
  assert.deepEqual(body(post(env.calls)[0]), {
    schema: "stpd/project-export-request-v1",
    collections: [uploadId],
    artifacts: [],
  });
  assert.equal(
    post(env.calls)[0].options.headers["X-CSRF-Token"],
    "local-csrf",
  );
  assert.match(text(env.notice), /文件尚未下载/);
  page = await env.render();
  assert.match(text(page), /1 \/ 2/);
  assert.match(text(page), /42 B \/ 84 B/);
  assert.doesNotMatch(text(page), /所选文件已通过本机完整性校验/);
  await action(page, "export-download-" + id("c")).onclick();
  assert.ok(post(env.calls)[1].url.endsWith("/download"));
  assert.match(text(env.notice), /服务已接收下载请求/);
});

test("export artifact payloads require explicit selected own roles; manifest does not recursively select parents", async () => {
  const artifact = id("9"),
    env = setup({
      mode: "cloud",
      view: "downloads",
      handler: (url, options) => {
        if (url.includes("/collections?")) return emptyList();
        if (url.includes("/datasets/"))
          return {
            item: {
              artifact_id: artifact,
              kind: "dataset",
              parents: [{ artifact_id: id("8") }],
              payloads: [
                { role: "training", size: 42, sha256: id("7") },
                { role: "profile", size: 12, sha256: id("6") },
              ],
            },
          };
        return exportManifest;
      },
    });
  let page = await env.render();
  field(page, "artifact-id").value = artifact;
  await action(page, "inspect-export-artifact").onclick();
  page = await env.render();
  const manifest = field(page, "artifact-" + artifact),
    payload = field(page, "role-training");
  assert.equal(payload.disabled, true);
  manifest.checked = true;
  manifest.onchange();
  payload.checked = true;
  payload.onchange();
  await action(page, "create-export").onclick();
  assert.deepEqual(body(post(env.calls)[0]), {
    schema: "stpd/project-export-request-v1",
    collections: [],
    artifacts: [{ artifact_id: artifact, roles: ["training"] }],
    csrf_token: "local-csrf",
  });
});

test("cloud export links are fixed same-origin file identities and malformed identities fail closed", async () => {
  const env = setup({
    mode: "cloud",
    view: "downloads",
    query: "&id=" + id("c"),
    handler: () => exportManifest,
  });
  const page = await env.render();
  const download = find(page, (node) => node.textContent === "下载此文件");
  assert.equal(
    download.href,
    "/app/api/member/exports/" + id("c") + "/files/" + id("d"),
  );
  assert.equal(env.calls.length, 1);
  assert.ok(env.calls.every((call) => !call.url.includes("local-models")));
  env.navigate("downloads", "&id=../../secret");
  const broken = await env.render();
  assert.match(text(broken), /invalid_export_identity/);
  assert.equal(env.calls.length, 1);
});

function modelHandler(url, options) {
  if (url === "/api/local-models")
    return {
      policies: [{ selection_id: "audited-cpu", label: "Reviewed CPU" }],
      downloaded_models: [],
      evaluations: [],
    };
  if (url === "/api/local-models/status")
    return { status: "idle", loaded: false, operation: null };
  if (url.includes("/readiness?"))
    return {
      selection_id: "audited-cpu",
      status: "ready_to_load",
      checks: { package: { status: "pass" } },
    };
  if (options.method === "POST")
    return {
      status: "pending",
      operation: { action: "start", status: "pending" },
    };
  return emptyList();
}
test("runtime uses dynamic trusted selections and readiness query, with load separate from readiness", async () => {
  const env = setup({ view: "local-models", handler: modelHandler });
  let page = await env.render();
  assert.equal(action(page, "model-start-audited-cpu").disabled, true);
  await action(page, "model-readiness-audited-cpu").onclick();
  assert.ok(
    env.calls.some(
      (call) =>
        call.url === "/api/local-models/readiness?selection_id=audited-cpu",
    ),
  );
  page = await env.render();
  assert.equal(action(page, "model-start-audited-cpu").disabled, false);
  assert.match(text(page), /不代表模型已经加载/);
  await action(page, "model-start-audited-cpu").onclick();
  assert.deepEqual(body(post(env.calls)[0]), { selection_id: "audited-cpu" });
  assert.match(text(env.notice), /尚需完成实际加载/);
});

test("unknown or stale runtime state permits explicit recovery but never another game decision", async () => {
  for (const state of [
    {
      status: "command_unknown",
      loaded: true,
      operation: { status: "unknown" },
      runtime: { mode: "auto", tainted: false },
    },
    {
      status: "loaded",
      loaded: true,
      observation_error: "unavailable",
      runtime: { mode: "auto" },
    },
    {
      status: "recovery_required",
      loaded: false,
      previous_session: { run_id: "previous" },
    },
  ]) {
    const env = setup({
        view: "local-models",
        handler: (url, options) =>
          url === "/api/local-models/status"
            ? state
            : modelHandler(url, options),
      }),
      page = await env.render();
    for (const name of ["auto", "one_step", "shadow"])
      assert.equal(action(page, "model-command-" + name).disabled, true);
    for (const name of ["human", "stop"])
      assert.equal(action(page, "model-command-" + name).disabled, false);
    await action(page, "model-command-auto").onclick();
    assert.equal(post(env.calls).length, 0);
    await action(page, "model-command-human").onclick();
    assert.deepEqual(body(post(env.calls)[0]), { action: "human" });
  }
});

test("cloud local-models view does not call or control any local service", async () => {
  const env = setup({ mode: "cloud", view: "local-models" }),
    page = await env.render();
  assert.equal(env.calls.length, 0);
  assert.match(text(page), /云页面不会远程启动或控制游戏/);
});

test("game-changing requests require confirmation and network ambiguity never auto retries", async () => {
  const env = setup({
      view: "local-models",
      handler: (url, options) => {
        if (url === "/api/local-models/status")
          return {
            status: "loaded",
            loaded: true,
            runtime: { mode: "human", lifecycle: "running" },
          };
        if (options.method === "POST") throw new Error("network lost");
        return modelHandler(url, options);
      },
    }),
    page = await env.render();
  await action(page, "model-command-one_step").onclick();
  assert.equal(env.confirms.length, 1);
  assert.equal(post(env.calls).length, 1);
  assert.match(text(env.notice), /不会自动重发/);
  assert.equal(env.reloads, 0);
});

test("late account mutation response cannot repaint notices or retain exports for the next account", async () => {
  let finish;
  const env = setup({
    view: "downloads",
    handler: (url, options) => {
      if (url.includes("/collections?"))
        return { items: [{ id: uploadId, status: "verified" }], total: 1 };
      if (options.method === "POST")
        return new Promise((resolve) => {
          finish = resolve;
        });
      return { status: "idle" };
    },
  });
  let page = await env.render();
  const item = field(page, "collection-" + uploadId);
  item.checked = true;
  item.onchange();
  const operation = action(page, "create-export").onclick();
  await new Promise((resolve) => setImmediate(resolve));
  env.account(owner("member", "next"));
  page = await env.render();
  finish(exportManifest);
  await operation;
  assert.equal(text(env.notice), "");
  assert.equal(env.reloads, 0);
  assert.equal(field(page, "collection-" + uploadId).checked, false);
  page = await env.render();
  assert.equal(
    walk(page).some((n) => n.dataset?.action === "export-download-" + id("c")),
    false,
  );
});

test("research category read failures preserve other categories and do not become empty success", async () => {
  const env = setup({
      view: "research",
      handler: (url) => {
        if (url.includes("/training?")) throw new Error("network");
        if (url.includes("/evaluations?"))
          return {
            availability: "available",
            items: [
              {
                artifact_id: id("3"),
                kind: "offline_evaluation",
                metadata: { records: 14 },
                payload_bytes: 10,
              },
            ],
            total: 1,
          };
        return emptyList();
      },
    }),
    page = await env.render();
  assert.match(text(page), /暂时无法读取此目录/);
  assert.match(text(page), /离线评估/);
  assert.match(text(page), /暂无已索引记录/);
  assert.equal(env.calls.length, 3);
});

test("a loaded service flag without a running Runtime observation cannot enable decisions", async () => {
  for (const runtime of [null, { lifecycle: "stopped", mode: "human" }]) {
    const env = setup({
      view: "local-models",
      handler: (url, options) =>
        url === "/api/local-models/status"
          ? { status: "loaded", loaded: true, runtime }
          : modelHandler(url, options),
    });
    const page = await env.render();
    assert.equal(action(page, "model-command-one_step").disabled, true);
    assert.equal(action(page, "model-command-human").disabled, false);
  }
});

test("prepared persisted enrollment remains visible when its older template is outside the current template page", async () => {
  const env = setup({
    view: "campaigns",
    handler: (url, options) => {
      if (url.includes("/enrollments?"))
        return { items: [enrollment], total: 1 };
      if (url.endsWith("/prepare"))
        return {
          status: "native_binding_required",
          native_binding_verified: false,
          delivery_started: false,
        };
      return { templates: [], total: 0 };
    },
  });
  let page = await env.render();
  await action(page, "prepare-" + enrollmentId).onclick();
  page = await env.render();
  assert.match(text(page), /需要精确原生绑定/);
});
