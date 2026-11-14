/* Pokémon FireRed 3DS - the web builder's worker.

   Runs the project's own builder (builder/firered3ds_builder, the same code
   as the Windows builder) under Pyodide, on the files of this version's
   FireRed3DS-WebPayload.zip, served by this site next to its
   web-manifest.json. The ROM arrives from the page, lives only in this
   worker's memory, and the ZIP for the SD card goes back to the page.

   Messages to the page: phase, progress, log, followers-list, done, error.
   From the page: start, followers. */

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";

const post = (msg, transfer) => self.postMessage(msg, transfer || []);
let followersArrived;
const followersMessage = new Promise((resolve) => { followersArrived = resolve; });

class Failure extends Error {
  constructor(code, message, hint) {
    super(message || code);
    this.code = code;
    this.hint = hint || "";
  }
}

self.onmessage = (e) => {
  const m = e.data;
  if (m.type === "start") {
    run(m).catch((err) => {
      if (err instanceof Failure) return post({ type: "error", code: err.code, message: err.message, hint: err.hint });
      const text = String(err && err.stack ? err.stack : err);
      const memory = /out of memory|memory access out of bounds|Array buffer allocation failed|MemoryError/i.test(text);
      post({ type: "error", code: memory ? "insufficient_memory" : "internal_error", message: "", hint: text.slice(-1200) });
    });
  } else if (m.type === "followers") {
    followersArrived(m);
  }
};

async function download(url, stage) {
  let r;
  try {
    r = await fetch(url, { credentials: "same-origin" });
  } catch (e) {
    throw new Failure("network", "", String(e));
  }
  if (!r.ok || !r.body) throw new Failure(r.status === 404 ? "payload_missing" : "network", "", "HTTP " + r.status + " " + url);
  const total = Number(r.headers.get("content-length")) || 0;
  const reader = r.body.getReader();
  const parts = [];
  let got = 0;
  let shown = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    got += value.length;
    if (total && got - shown > 262144) {
      shown = got;
      post({ type: "progress", stage, fraction: got / total,
             detail: (got / 1048576).toFixed(1) + " / " + (total / 1048576).toFixed(1) + " MB" });
    }
  }
  const out = new Uint8Array(got);
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  post({ type: "progress", stage, fraction: 1, detail: (got / 1048576).toFixed(1) + " MB" });
  return out;
}

async function loadRuntime() {
  let py;
  try {
    const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
    post({ type: "progress", stage: "runtime", fraction: 0.4 });
    py = await loadPyodide({
      indexURL: PYODIDE,
      stdout: (line) => post({ type: "log", line }),
      stderr: (line) => post({ type: "log", line }),
    });
    post({ type: "progress", stage: "runtime", fraction: 0.75 });
    await py.loadPackage(["pillow"], {
      messageCallback: (line) => post({ type: "log", line }),
      errorCallback: (line) => post({ type: "log", line }),
    });
    try { py.runPython("import lzma"); } catch (e) { await py.loadPackage("lzma"); }
  } catch (e) {
    if (e instanceof Failure) throw e;
    throw new Failure("network", "", "Python could not be loaded: " + e);
  }
  post({ type: "progress", stage: "runtime", fraction: 1 });
  return py;
}

// Unpack the payload into /fr3ds, checking every file against the manifest.
const UNPACK = `
import hashlib, json, sys, zipfile
from pathlib import Path
root = Path("/fr3ds")
with zipfile.ZipFile(root / "payload.zip") as zf:
    manifest = json.loads(zf.read("web-manifest.json"))
    for item in manifest["files"]:
        data = zf.read(item["path"])
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("damaged payload file: " + item["path"])
        out = root / item["path"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
(root / "web-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
(root / "payload.zip").unlink()
sys.path.insert(0, str(root / manifest["entrypoint"]["pythonPath"]))
json.dumps({"tag": manifest["releaseTag"], "files": len(manifest["files"])})
`;

function mkdirs(py, path) {
  const dir = path.slice(0, path.lastIndexOf("/"));
  if (dir) py.FS.mkdirTree(dir);
}

async function run({ base, rom, romName, followers }) {
  const t0 = performance.now();
  post({ type: "phase", phase: "runtime" });
  const py = await loadRuntime();
  post({ type: "log", line: "Python " + py.runPython("import sys; sys.version.split()[0]") + ", Pyodide " + py.version });

  post({ type: "phase", phase: "payload" });
  let manifest;
  try {
    const r = await fetch(base + "payload/web-manifest.json", { cache: "no-cache" });
    if (!r.ok) throw new Failure("payload_missing", "", "HTTP " + r.status);
    manifest = await r.json();
  } catch (e) {
    throw e instanceof Failure ? e : new Failure("network", "", String(e));
  }
  if (manifest.schemaVersion !== 1 || manifest.kind !== "firered3ds-web-payload") {
    throw new Failure("payload_missing", "", "unknown web manifest");
  }
  const zip = await download(base + "payload/FireRed3DS-WebPayload.zip?v=" + encodeURIComponent(manifest.releaseTag), "payload");
  py.FS.mkdirTree("/fr3ds");
  py.FS.writeFile("/fr3ds/payload.zip", zip);
  post({ type: "log", line: "payload: " + py.runPython(UNPACK) });

  if (followers) {
    // the page downloads the sprites while this worker builds
    const list = JSON.parse(py.runPython("from firered3ds_builder.web import follower_downloads\nfollower_downloads()"));
    post(Object.assign({ type: "followers-list" }, list));
  }

  const name = /\.zip$/i.test(romName) ? "rom.zip" : "rom.gba";
  py.FS.mkdirTree("/rom");
  py.FS.writeFile("/rom/" + name, new Uint8Array(rom));
  rom = null;

  post({ type: "phase", phase: "data" });
  py.globals.set("js_progress", (stage, fraction, message) => post({ type: "progress", stage, fraction, message }));
  py.globals.set("rom_path", "/rom/" + name);
  const built = JSON.parse(py.runPython(`
from firered3ds_builder.web import run_web_build
run_web_build(rom_path, "/fr3ds/payload", "/sd/3ds/firered3ds/firered3ds.pak", js_progress, "/fr3ds/web-manifest.json")
`));
  py.FS.unlink("/rom/" + name);
  if (!built.ok) throw new Failure(built.error.code, built.error.message, built.error.hint);
  post({ type: "log", line: "pack: " + JSON.stringify(built.result) });
  py.globals.set("rom_sha1", built.result.romSha1);
  py.runPython(`
from firered3ds_builder.web import copy_executables
copy_executables("/fr3ds/payload", rom_sha1, "/sd/3ds/firered3ds")
`);

  let followersOk = false;
  if (followers) {
    post({ type: "phase", phase: "followers" });
    const m = await followersMessage;
    if (!m.failed) {
      for (const [path, data] of m.files) {
        const full = "/cache/" + path + (data ? "" : ".missing");
        mkdirs(py, full);
        py.FS.writeFile(full, data ? new Uint8Array(data) : new Uint8Array(0));
      }
      const res = JSON.parse(py.runPython(`
import shutil
from firered3ds_builder.web import run_web_followers
_res = run_web_followers("/cache", "/sd/3ds/firered3ds", js_progress)
shutil.rmtree("/cache", ignore_errors=True)
_res
`));
      followersOk = res.ok;
      if (!res.ok) post({ type: "log", line: "followers: " + JSON.stringify(res.error) });
    }
  }

  post({ type: "phase", phase: "zip" });
  py.runPython(`
from firered3ds_builder.web import make_sd_zip
make_sd_zip("/sd", "/out.zip")
`);
  const out = py.FS.readFile("/out.zip");
  const buffer = out.buffer.byteLength === out.byteLength ? out.buffer : out.slice().buffer;
  post({ type: "log", line: "done in " + ((performance.now() - t0) / 1000).toFixed(1) + " s" });
  post({ type: "done", zip: buffer, result: built.result, followers: followersOk }, [buffer]);
}
