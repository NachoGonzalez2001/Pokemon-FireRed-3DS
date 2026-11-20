/* Pokémon FireRed 3DS - the guide: where each wild Pokémon lives.
   data/wild.json is made by tools/build_wild_guide.py from the port's tables. */
(function () {
  "use strict";
  const { t } = window.FR3DS;
  const $ = (s) => document.querySelector(s);
  const METHODS = ["land", "surf", "old", "good", "super", "rock"];

  let data = null;
  let tab = "places";
  let group = "all";
  let query = "";

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function fold(s) {
    return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }
  function placeName(a) { return a.sub ? a.name + " · " + a.sub : a.name; }
  function levels(e) { return e.min === e.max ? t("g.lv", { n: e.min }) : t("g.lvs", { a: e.min, b: e.max }); }
  function dexNo(n) { return "#" + String(n).padStart(3, "0"); }
  function types(list) {
    const box = el("span", "types");
    list.forEach((ty) => box.append(el("span", "type t-" + ty, t("type." + ty))));
    return box;
  }
  function groupLabel(a) {
    return a.group === "sevii" ? t("g.island", { n: a.island }) : t("g." + a.group);
  }

  // Every place a species lives in, built once from the places.
  function index() {
    const where = {};
    for (const a of data.areas) {
      for (const m of METHODS) {
        for (const e of a.methods[m] || []) {
          (where[e.s] = where[e.s] || []).push({ area: a, method: m, e });
        }
      }
    }
    return where;
  }

  function matchesArea(a, q) {
    if (!q) return true;
    if (fold(placeName(a)).includes(q)) return true;
    return METHODS.some((m) => (a.methods[m] || []).some((e) => speciesMatch(e.s, q)));
  }
  function speciesMatch(id, q) {
    const sp = data.species[id];
    return fold(sp.name).includes(q) || String(sp.dex) === q.replace(/^#?0*/, "");
  }

  function renderPlaces() {
    const q = fold(query.trim());
    const box = $("[data-places]");
    const frag = document.createDocumentFragment();
    let shown = 0;
    let lastHeading = "";
    for (const a of data.areas) {
      if (group !== "all" && a.group !== group) continue;
      if (!matchesArea(a, q)) continue;
      const heading = groupLabel(a);
      if (heading !== lastHeading) {
        frag.append(el("h2", "group-title", heading));
        lastHeading = heading;
      }
      shown++;
      const card = el("article", "card place");
      card.id = a.id;
      const h = el("h3", null, a.name);
      if (a.sub) h.append(el("span", "sub", a.sub));
      card.append(h);
      for (const m of METHODS) {
        const list = a.methods[m];
        if (!list) continue;
        const table = el("table", "slots");
        const cap = el("caption");
        cap.append(el("span", "method m-" + m, t("m." + m)));
        table.append(cap);
        const body = el("tbody");
        for (const e of list) {
          const sp = data.species[e.s];
          const tr = el("tr");
          if (q && speciesMatch(e.s, q)) tr.className = "hit";
          tr.append(el("td", "dex", dexNo(sp.dex)));
          const name = el("td", "name");
          const link = el("a", null, sp.name);
          link.href = "#mon-" + e.s.toLowerCase();
          link.addEventListener("click", (ev) => { ev.preventDefault(); showSpecies(sp.name); });
          name.append(link, types(sp.types));
          tr.append(name, el("td", "lv", levels(e)), el("td", "rate", e.rate + "%"));
          body.append(tr);
        }
        table.append(body);
        card.append(table);
      }
      frag.append(card);
    }
    box.replaceChildren(frag);
    return shown;
  }

  let where = null;
  function renderSpecies() {
    const q = fold(query.trim());
    const box = $("[data-mons]");
    const frag = document.createDocumentFragment();
    let shown = 0;
    for (const id in data.species) {
      const sp = data.species[id];
      let spots = where[id] || [];
      if (group !== "all") spots = spots.filter((w) => w.area.group === group);
      if (!spots.length) continue;
      const placeHit = q && !speciesMatch(id, q);
      if (placeHit) spots = spots.filter((w) => fold(placeName(w.area)).includes(q));
      if (q && !spots.length) continue;
      shown++;
      const card = el("article", "card mon");
      card.id = "mon-" + id.toLowerCase();
      const h = el("h3");
      h.append(el("span", "dex", dexNo(sp.dex)), el("span", null, sp.name), types(sp.types));
      card.append(h);
      const ul = el("ul", "spots");
      spots.sort((x, y) => y.e.rate - x.e.rate || x.e.min - y.e.min);
      for (const w of spots) {
        const li = el("li");
        const link = el("a", null, placeName(w.area));
        link.href = "#" + w.area.id;
        link.addEventListener("click", (ev) => { ev.preventDefault(); showPlace(w.area); });
        li.append(link, el("span", "method m-" + w.method, t("m." + w.method)),
          el("span", "lv", levels(w.e)), el("span", "rate", w.e.rate + "%"));
        ul.append(li);
      }
      card.append(ul);
      frag.append(card);
    }
    box.replaceChildren(frag);
    return shown;
  }

  function render() {
    if (!data) return;
    const places = tab === "places";
    $("[data-places]").classList.toggle("hidden", !places);
    $("[data-mons]").classList.toggle("hidden", places);
    const n = places ? renderPlaces() : renderSpecies();
    $("[data-empty]").classList.toggle("hidden", n > 0);
    $("[data-count]").textContent = t(places ? "g.nplaces" : "g.nmons", { n });
  }

  function setTab(next) {
    tab = next;
    document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    render();
  }
  // guide.html#route1 opens a place, guide.html#mon-pikachu a Pokémon.
  function followHash() {
    const hash = decodeURIComponent(location.hash.slice(1)).toLowerCase();
    if (!hash) return;
    query = ""; $("[data-search]").value = "";
    setGroup("all");
    setTab(hash.startsWith("mon-") ? "species" : "places");
    jump(hash);
  }
  function setGroup(next) {
    group = next;
    document.querySelectorAll("[data-group]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.group === group)));
    render();
  }
  function jump(id) {
    const target = document.getElementById(id);
    if (!target) return;
    const top = target.getBoundingClientRect().top + window.scrollY - 76;
    window.scrollTo({ top, behavior: "instant" });
    target.classList.remove("flash");
    void target.offsetWidth;
    target.classList.add("flash");
  }
  function showSpecies(name) {
    const id = Object.keys(data.species).find((k) => data.species[k].name === name);
    query = ""; $("[data-search]").value = "";
    setGroup("all");
    setTab("species");
    jump("mon-" + id.toLowerCase());
  }
  function showPlace(area) {
    query = ""; $("[data-search]").value = "";
    setGroup("all");
    setTab("places");
    jump(area.id);
  }

  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  document.querySelectorAll("[data-group]").forEach((b) => b.addEventListener("click", () => setGroup(b.dataset.group)));
  let timer = 0;
  $("[data-search]").addEventListener("input", (ev) => {
    clearTimeout(timer);
    timer = setTimeout(() => { query = ev.target.value; render(); }, 120);
  });

  window.FR3DS.onLang(render);

  fetch("data/wild.json")
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((json) => {
      data = json;
      where = index();
      render();
      followHash();
      window.addEventListener("hashchange", followHash);
    })
    .catch(() => {
      $("[data-count]").textContent = t("g.error");
    });
})();
