/* Pokémon FireRed 3DS - the web builder's page.

   The ROM is checked here (SHA-1, on this device) and handed to
   builder.worker.js, which runs the project's own Python builder under
   Pyodide. While the worker builds, this page downloads the follower's
   sprites from PMD SpriteCollab (kept in the browser's cache for the next
   time) and gives them to the worker when it is ready for them. Nothing is
   ever sent anywhere: the only requests are downloads. */

const { t, release, onLang } = window.FR3DS;
const $ = (sel) => document.querySelector(sel);

const ROM_SIZE = 16 * 1024 * 1024;
const KNOWN = {
  BPRE: "Pokémon FireRed (USA)", BPRJ: "Pokémon FireRed (Japan)", BPRS: "Pokémon Rojo Fuego (Spain)",
  BPRD: "Pokémon Feuerrote Edition (Germany)", BPRF: "Pokémon Rouge Feu (France)", BPRI: "Pokémon Rosso Fuoco (Italy)",
  BPGE: "Pokémon LeafGreen", BPEE: "Pokémon Emerald", AXVE: "Pokémon Ruby", AXPE: "Pokémon Sapphire",
};
const PHASES = ["runtime", "payload", "data", "scenery", "verify", "followers", "zip"];
// each phase's share of the bar, roughly its share of the time
const WEIGHT = { runtime: 0.07, payload: 0.03, data: 0.04, scenery: 0.66, verify: 0.03, followers: 0.13, zip: 0.04 };
const STEP_LABEL = { "terrain relief": "s.terrain relief", "trees": "s.trees", "buildings": "s.buildings" };

const state = { file: null, bytes: null, ok: false, manifest: null, info: null, worker: null, url: null };
const frac = {};
let followersOn = true;
let timer = null;
let wakeLock = null;
let started = 0;
let lastError = null;

/* --- views ------------------------------------------------------------- */

function view(name) {
  document.querySelectorAll("[data-view]").forEach((el) => el.classList.toggle("hidden", el.dataset.view !== name));
}

function log(line) {
  const pre = $("[data-log]");
  pre.textContent += line + "\n";
  pre.scrollTop = pre.scrollHeight;
}

function romStatus(kind, title, hint, hash) {
  const box = $("[data-rom-status]");
  const icon = kind === "ok"
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></svg>'
    : kind === "err"
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>';
  box.className = "status " + (kind === "info" ? "" : kind);
  box.innerHTML = icon + "<div><strong></strong><div class='small'></div><div class='hash'></div></div>";
  box.querySelector("strong").textContent = title;
  box.querySelector(".small").textContent = hint || "";
  box.querySelector(".hash").textContent = hash ? "SHA-1 " + hash : "";
}

/* --- the ROM ----------------------------------------------------------- */

function supportedSha1s() {
  const m = state.manifest;
  if (!m) return [];
  return m.supportedRoms.map((r) => r.sha1).concat((m.variants || []).map((v) => v.rom.sha1));
}

async function sha1Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-1", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

let romCheck = null;   // the last check; a stale one never wins
let lastRom = null;    // the last ROM given, checked again when the language changes

async function checkRom(file) {
  lastRom = file;
  const mine = (romCheck = {});
  state.ok = false;
  updateStart();
  state.file = file;
  romStatus("info", t("rom.reading"));
  if (file.size === 0) return romStatus("err", t("rom_empty"));
  if (/\.zip$/i.test(file.name)) {
    if (file.size > 64 * 1024 * 1024) return romStatus("err", t("rom_too_large"));
    state.bytes = await file.arrayBuffer();
    if (mine !== romCheck) return;
    state.ok = true;
    romStatus("ok", t("rom.zip"));
    return updateStart();
  }
  if (file.size > ROM_SIZE) return romStatus("err", t("rom_too_large"));
  const raw = new Uint8Array(await file.arrayBuffer());
  const full = new Uint8Array(ROM_SIZE).fill(0xff);   // a trimmed dump: its trailing 0xFF fill put back
  full.set(raw);
  const sha1 = await sha1Hex(full);
  if (mine !== romCheck) return;
  const code = String.fromCharCode(...full.subarray(0xac, 0xb0));
  if (supportedSha1s().includes(sha1)) {
    state.bytes = full.buffer;
    state.ok = true;
    // Each language has its own build in the release: say which one this ROM gets.
    const m = state.manifest;
    const rom = m.supportedRoms.concat((m.variants || []).map((v) => v.rom)).find((r) => r.sha1 === sha1);
    romStatus("ok", t("rom.ok"), (rom && rom.name ? rom.name + " · " : "") + file.name, sha1);
  } else if (code === "BPRE") {
    romStatus("err", t("rom_modified"), t("rom_modified.hint"), sha1);
  } else if (KNOWN[code]) {
    romStatus("err", t("rom_wrong_game", { game: KNOWN[code] }), "", sha1);
  } else {
    romStatus("err", t("rom_unsupported"), t("rom_unsupported.hint"), sha1);
  }
  updateStart();
}

function updateStart() {
  $("[data-start]").disabled = !(state.ok && state.manifest);
}

/* --- the follower's sprites --------------------------------------------- */

async function fetchRetry(url, tries = 4) {
  for (let i = 0; ; i++) {
    try {
      const r = await fetch(url, { mode: "cors", credentials: "omit" });
      if (r.ok || r.status === 404 || i === tries - 1) return r;
    } catch (e) {
      if (i === tries - 1) throw e;
    }
    await new Promise((res) => setTimeout(res, 600 * (i + 1)));
  }
}

async function downloadFollowers(list, onProgress) {
  let cache = null;
  try { cache = await caches.open("fr3ds-spritecollab-" + list.commit.slice(0, 12)); } catch (e) { /* no Cache Storage */ }
  const out = new Array(list.files.length);
  let next = 0;
  let done = 0;
  async function lane() {
    while (next < list.files.length) {
      const i = next++;
      const url = list.source + list.files[i];
      let r = null;
      if (cache) { try { r = await cache.match(url); } catch (e) { r = null; } }
      if (!r) {
        r = await fetchRetry(url);
        if (cache && (r.ok || r.status === 404)) { try { await cache.put(url, r.clone()); } catch (e) { /* full */ } }
      }
      if (r.status === 404) out[i] = null;
      else if (!r.ok) throw new Error("HTTP " + r.status + " " + list.files[i]);
      else out[i] = await r.arrayBuffer();
      done++;
      if (done % 40 === 0 || done === out.length) onProgress(done, out.length);
    }
  }
  await Promise.all(Array.from({ length: 12 }, lane));
  return out;
}

/* --- the build --------------------------------------------------------- */

function setPhase(phase, cls) {
  const li = document.querySelector('[data-phase="' + phase + '"]');
  if (li) li.className = cls;
}

function activate(phase) {
  const at = PHASES.indexOf(phase);
  PHASES.forEach((p, i) => {
    const li = document.querySelector('[data-phase="' + p + '"]');
    if (li.classList.contains("skip")) return;
    if (i < at) { li.className = "done"; frac[p] = 1; }
    else if (i === at) li.className = "active";
  });
  render();
}

function detail(phase, text) {
  const el = document.querySelector('[data-phase="' + phase + '"] .detail');
  if (el) el.textContent = text;
}

function render() {
  let total = 0;
  for (const p of PHASES) total += WEIGHT[p] * (frac[p] || 0);
  const pct = Math.min(100, Math.round(total * 100));
  $("[data-bar]").style.width = pct + "%";
  $("[data-bar-text]").textContent = pct + "%";
}

function clock() {
  const s = Math.floor((performance.now() - started) / 1000);
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

function sceneryDetail(message) {
  const m = /: (.+?) \((\d+)\/(\d+)\)/.exec(message || "");
  if (!m) return "";
  return t(STEP_LABEL[m[1]] || m[1]) + " (" + m[2] + "/" + m[3] + ")";
}

function onProgress(msg) {
  const phase = msg.stage === "rom" ? "data" : msg.stage;
  if (phase === "scenery") {
    // the overall 0.5..0.9 of the Python build is the 3D world
    frac.data = 1;
    frac.scenery = Math.max(0, Math.min(1, (msg.fraction - 0.5) / 0.4));
    const d = sceneryDetail(msg.message);
    if (d) detail("scenery", d);
  } else if (phase === "data") {
    frac.data = Math.min(1, msg.fraction / 0.5);
  } else if (phase === "verify") {
    frac.scenery = 1;
    frac.verify = Math.max(0, Math.min(1, (msg.fraction - 0.9) / 0.1));
  } else if (phase === "followers") {
    frac.followers = 0.5 + 0.5 * msg.fraction;
    detail("followers", t("p.packing") + " " + Math.round(msg.fraction * 100) + "%");
  }
  const li = document.querySelector('[data-phase="' + phase + '"]');
  if (li && !li.classList.contains("active") && !li.classList.contains("done")) activate(phase);
  render();
}

async function acquireWakeLock() {
  try { wakeLock = await navigator.wakeLock.request("screen"); } catch (e) { wakeLock = null; }
}

function stopRun() {
  clearInterval(timer);
  if (wakeLock) { wakeLock.release().catch(() => {}); wakeLock = null; }
  if (state.worker) { state.worker.terminate(); state.worker = null; }
}

function fail(code, message, hint) {
  stopRun();
  lastError = { code, message, hint };
  showError();
  view("error");
}

function showError() {
  if (!lastError) return;
  const { code, message, hint } = lastError;
  const known = {
    network: ["e.network", null], insufficient_memory: ["e.memory", "e.memory.hint"],
    unsupported_browser: ["e.unsupported", "e.unsupported.hint"], payload_missing: ["e.nopayload", null],
    rom_modified: ["rom_modified", "rom_modified.hint"], rom_unsupported: ["rom_unsupported", "rom_unsupported.hint"],
    rom_too_large: ["rom_too_large", null], rom_empty: ["rom_empty", null],
  };
  const k = known[code];
  $("[data-error-title]").textContent = k ? t(k[0]) : (message || t("e.internal"));
  $("[data-error-hint]").textContent = k && k[1] ? t(k[1]) : (hint || "");
}

function start() {
  if (!state.ok || !state.manifest) return;
  if (typeof Worker === "undefined" || !window.crypto || !crypto.subtle) return fail("unsupported_browser");
  followersOn = $("[data-followers]").checked;
  lastError = null;
  $("[data-log]").textContent = "";
  PHASES.forEach((p) => { frac[p] = 0; detail(p, ""); setPhase(p, ""); });
  if (!followersOn) { setPhase("followers", "skip"); frac.followers = 1; detail("followers", t("p.skipped")); }
  view("run");
  render();
  started = performance.now();
  timer = setInterval(() => { $("[data-elapsed]").textContent = clock(); }, 500);
  acquireWakeLock();

  const worker = new Worker(new URL("./builder.worker.js", import.meta.url), { type: "module" });
  state.worker = worker;
  let followerJob = null;
  worker.onerror = (e) => fail("internal_error", t("e.internal"), e.message || "");
  worker.onmessage = (e) => {
    const m = e.data;
    if (m.type === "log") log(m.line);
    else if (m.type === "phase") { activate(m.phase); if (m.detail) detail(m.phase, m.detail); }
    else if (m.type === "progress") {
      if (m.stage === "runtime" || m.stage === "payload") {
        frac[m.stage] = m.fraction;
        if (m.detail) detail(m.stage, m.detail);
        render();
      } else onProgress(m);
    } else if (m.type === "followers-list") {
      followerJob = downloadFollowers(m, (done, total) => {
        frac.followers = 0.5 * done / total;
        if (!document.querySelector('[data-phase="followers"]').classList.contains("active"))
          detail("followers", t("p.downloading", { done, total }));
        render();
      }).then((files) => {
        const buffers = files.filter((b) => b);
        worker.postMessage({ type: "followers", files: m.files.map((p, i) => [p, files[i]]) }, buffers);
      }, (err) => {
        log("followers: " + err);
        worker.postMessage({ type: "followers", failed: true });
      });
    } else if (m.type === "done") finish(m);
    else if (m.type === "error") { log("error: " + m.code + " " + (m.message || "") + " " + (m.hint || "")); fail(m.code, m.message, m.hint); }
  };
  // the worker gets its own copy: the page keeps the ROM for "Build again"
  const rom = state.bytes.slice(0);
  worker.postMessage({ type: "start", base: new URL("../../", import.meta.url).href, rom, romName: state.file.name,
                       followers: followersOn }, [rom]);
}

async function finish(m) {
  stopRun();
  PHASES.forEach((p) => { if (!document.querySelector('[data-phase="' + p + '"]').classList.contains("skip")) setPhase(p, "done"); frac[p] = 1; });
  render();
  const info = state.info || {};
  const tag = (state.manifest && state.manifest.releaseTag) || info.tag || "";
  const name = "FireRed3DS-" + tag + "-SD.zip";
  if (state.url) URL.revokeObjectURL(state.url);
  state.url = URL.createObjectURL(new Blob([m.zip], { type: "application/zip" }));
  const a = $("[data-download]");
  a.href = state.url;
  a.download = name;
  const mb = (m.zip.byteLength / 1048576).toFixed(1) + " MB";
  state.done = { name, mb, time: clock(), followers: m.followers };
  doneText();
  view("done");
  a.click();
}

function doneText() {
  if (!state.done) return;
  $("[data-done-summary]").textContent = t("d.summary", { name: state.done.name, size: state.done.mb, time: state.done.time });
  $("[data-done-warn]").textContent = followersOn && !state.done.followers ? t("d.nofollowers") : "";
}

function showCia(info) {
  const url = info && info.assets && info.assets.cia;
  if (!url) return;
  $("[data-cia]").classList.remove("hidden");
  const link = $("[data-cia-link]");
  link.href = url;
  link.textContent = url.split("/").pop();
  const draw = () => {
    if (!window.qrcode) return false;
    const qr = window.qrcode(0, "M");
    qr.addData(url);
    qr.make();
    $("[data-qr]").innerHTML = qr.createImgTag(4, 8, "QR: " + url);
    return true;
  };
  if (!draw()) window.addEventListener("load", draw, { once: true });
}

/* --- wiring ------------------------------------------------------------ */

const input = $("[data-rom]");
const drop = $("[data-drop]");
input.addEventListener("change", () => { if (input.files[0]) checkRom(input.files[0]); });
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  const f = e.dataTransfer.files[0];
  if (f) checkRom(f);
});
$("[data-start]").addEventListener("click", start);
document.querySelectorAll("[data-again]").forEach((b) => b.addEventListener("click", () => { view("pick"); updateStart(); }));
window.addEventListener("beforeunload", (e) => { if (state.worker) { e.preventDefault(); e.returnValue = ""; } });

onLang(() => {
  if (lastRom && !state.worker) checkRom(lastRom);
  showError();
  doneText();
  if (!followersOn) detail("followers", t("p.skipped"));
});

fetch("payload/web-manifest.json", { cache: "no-cache" })
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
  .then((m) => {
    if (m.schemaVersion !== 1 || m.kind !== "firered3ds-web-payload") throw new Error("unknown manifest");
    state.manifest = m;
    document.querySelectorAll('[data-release="tag"]').forEach((el) => { el.textContent = m.releaseTag; });
    if (lastRom) checkRom(lastRom);
    updateStart();
  })
  .catch((err) => { log("manifest: " + err); fail("payload_missing"); });

release.then((info) => { state.info = info; showCia(info); });
view("pick");
