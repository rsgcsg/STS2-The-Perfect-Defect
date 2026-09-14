import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.value = ''; this.dataset = {}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  get options() { return this.children; }
}
function setup() {
  const nodes = new Map(['account-actions', 'device-scope', 'content', 'notice'].map(k => [k, new Element('div')]));
  const calls = [];
  const context = vm.createContext({
    document: {body: {dataset: {mode: 'local'}}, getElementById: key => nodes.get(key),
      createElement: tag => new Element(tag), querySelector: () => null}, window: {},
    location: {assign() {}}, history: {pushState() {}}, Date, URLSearchParams, AbortSignal,
    setTimeout, clearTimeout,
    fetch: (url, options) => new Promise(resolve => calls.push({url, options,
      answer: body => resolve({ok:true, json: async () => body})})),
  });
  vm.runInContext(readFileSync(new URL('../stpd/console/identity.js', import.meta.url), 'utf8'), context);
  return {ui: context.window.SpireIdentity, nodes, calls};
}
const person = (subject = 'one') => ({status: 'signed_in', csrf_token: 'csrf',
  principal: {subject, email: subject + '@example.test'}, devices: [{device_id: 'pc', name: 'Laptop'}]});

test('account logout rejects an already in-flight identity response and retains local scope', async () => {
  const {ui, nodes, calls} = setup();
  const initial = ui.refresh(true); calls.shift().answer(person()); await initial;
  const pending = ui.refresh(true), old = calls.shift();
  const logout = nodes.get('account-actions').children.find(x => x.tag === 'button');
  const exiting = logout.onclick();
  assert.equal(nodes.get('account-actions').children.some(x => x.textContent === 'one@example.test'), false);
  old.answer(person()); await pending;
  assert.equal(nodes.get('account-actions').children.some(x => x.textContent === 'one@example.test'), false);
  calls.shift().answer({remote_revoked: true});
  await new Promise(resolve => setImmediate(resolve));
  calls.shift().answer({status:'signed_out', csrf_token:'csrf'});
  await exiting;
  assert.equal(ui.isLocal(), true);
  assert.match(ui.context(), /anonymous/);
});

test('device selection changes request scope and invalidates prior response context', async () => {
  const {ui, nodes, calls} = setup();
  const initial = ui.refresh(true); calls.shift().answer(person()); await initial;
  let reset = false; ui.connect(value => {reset = value;});
  const before = ui.context(), select = nodes.get('device-scope');
  select.value = 'pc'; select.onchange();
  assert.equal(reset, true);
  assert.notEqual(ui.context(), before);
  assert.equal(ui.isLocal(), false);
  assert.equal(ui.api('collections', '?limit=25'), '/api/project/collections?limit=25&device=pc');
});

function pageSetup(view, identity, connectContent = async () => 'connection facts', flow = '') {
  const nodes = new Map();
  const element = () => Object.assign(new Element('div'), {
    textContent: '', attributes: {}, addEventListener() {},
    setAttribute(name, value) { this.attributes[name] = value; },
  });
  const get = key => {
    if (!nodes.has(key)) nodes.set(key, element());
    return nodes.get(key);
  };
  get('connection').textContent = '正在读取状态…';
  let scope = 'owner';
  const context = vm.createContext({
    document: {body: {dataset: {mode: 'cloud'}}, getElementById: get,
      createElement: element, createDocumentFragment: element, querySelectorAll: () => [], addEventListener() {}},
    Node: Element,
    window: {addEventListener() {}, SpireProject: {}, SpireIdentity: {
      context: () => scope, isLocal: () => false, refresh: async () => identity,
      renderDevices: () => 'account facts', renderConnect: connectContent, connect() {},
    }},
    location: {search: '?view=' + view + (flow ? '&flow=' + flow : '')}, history: {}, Date, URLSearchParams,
    setInterval() {},
  });
  vm.runInContext(readFileSync(new URL('../stpd/console/console.js', import.meta.url), 'utf8'), context);
  return {get, context, changeScope: () => {scope = 'other';}};
}
const settled = () => new Promise(resolve => setImmediate(resolve));

test('account and connection pages finish status from observed identity', async () => {
  for (const view of ['devices', 'connect']) {
    const {get, context} = pageSetup(view, {status: 'signed_in', observed_at: '2026-09-13T11:00:00Z'});
    await settled();
    assert.equal(get('connection').textContent, '已通过身份验证');
    assert.match(get('updated').textContent, /^账号更新于 /);
    assert.doesNotMatch(get('updated').textContent, /未观测|尚未/);
    assert.equal(get('content').attributes['aria-busy'], 'false');
    assert.notEqual(vm.runInContext('renderedContext', context), null);
  }
});

test('account state does not invent authentication or an observation timestamp', async () => {
  for (const [status, label] of [['signed_out', '未登录项目账号'],
    ['reconnect_required', '需要重新登录'], ['unavailable', '账号状态暂不可用']]) {
    const {get} = pageSetup('devices', {status});
    await settled();
    assert.equal(get('connection').textContent, label);
    assert.equal(get('updated').textContent, '账号观测时间未提供');
  }
});

test('connection response cannot repaint a changed identity scope', async () => {
  let finish;
  const pending = new Promise(resolve => {finish = resolve;});
  const {get, changeScope} = pageSetup('connect', {status: 'signed_in'}, () => pending);
  await settled();
  changeScope(); finish('previous account private connection');
  await settled();
  assert.equal(get('content').children.includes('previous account private connection'), false);
  assert.notEqual(get('connection').textContent, '已通过身份验证');
});


test('switching connection flow removes the previous approval panel before its replacement arrives', async () => {
  let finish, calls = 0;
  const pending = new Promise(resolve => {finish = resolve;});
  const {get, context} = pageSetup('connect', {status: 'signed_in'},
    () => ++calls === 1 ? 'approval for first flow' : pending, 'a'.repeat(32));
  await settled();
  assert.deepEqual(get('content').children, ['approval for first flow']);
  context.location.search = '?view=connect&flow=' + 'b'.repeat(32);
  const loading = vm.runInContext('readLocation(); load(true)', context);
  await settled();
  assert.equal(get('content').children.includes('approval for first flow'), false);
  finish('approval for second flow'); await loading;
  assert.deepEqual(get('content').children, ['approval for second flow']);
});


test('system preserves capacity attention and missing observations without claiming backup success', async () => {
  const {context} = pageSetup('devices', {status: 'signed_in'});
  await settled();
  const flatten = element => [element.textContent || '', ...(element.children || []).map(
    child => typeof child === 'string' ? child : flatten(child))].join(' ');
  for (const [status, phrase] of [['attention', '容量不足'], ['unknown', '容量未完整观测']]) {
    context.capacityFixture = {storage: {free_bytes: null, total_bytes: null,
      capacity: {status, free_inodes: null, reserve_bytes: 6442450944, reserve_inodes: 100000}},
      backup: {availability: 'unavailable'}};
    const rendered = flatten(vm.runInContext('system(capacityFixture)', context)).replace(/\s+/g, ' ');
    assert.match(rendered, new RegExp(phrase));
    assert.match(rendered, /可用 \/ 总容量 未观测 \/ 未观测/);
    assert.match(rendered, /备份新鲜度 未观测/);
    assert.match(rendered, /不会自动删除数据或镜像/);
    assert.doesNotMatch(rendered, /运行余量充足|在有效期内/);
  }
});
