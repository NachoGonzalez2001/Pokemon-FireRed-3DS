/* Pokémon FireRed 3DS - shared page code: language, menu, release info. */
(function () {
  "use strict";
  const LANGS = ["en", "es"];
  const listeners = [];

  function stored() {
    try { return localStorage.getItem("fr3ds-lang"); } catch (e) { return null; }
  }
  function pickLang() {
    const s = stored();
    if (LANGS.includes(s)) return s;
    const nav = (navigator.language || "en").slice(0, 2).toLowerCase();
    return LANGS.includes(nav) ? nav : "en";
  }

  let lang = pickLang();

  function t(key, vars) {
    const dict = window.I18N[lang] || {};
    let s = key in dict ? dict[key] : (window.I18N.en[key] !== undefined ? window.I18N.en[key] : key);
    if (vars) for (const k in vars) s = s.split("{" + k + "}").join(vars[k]);
    return s;
  }

  function apply() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    listeners.forEach((fn) => fn(lang));
  }

  function setLang(next) {
    if (!LANGS.includes(next)) return;
    lang = next;
    try { localStorage.setItem("fr3ds-lang", next); } catch (e) { /* private mode */ }
    apply();
  }

  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));

  const menu = document.querySelector("[data-menu]");
  const nav = document.querySelector("[data-nav]");
  if (menu && nav) {
    menu.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      menu.setAttribute("aria-expanded", String(open));
    });
    nav.addEventListener("click", (e) => {
      if (e.target.closest("a")) { nav.classList.remove("open"); menu.setAttribute("aria-expanded", "false"); }
    });
  }

  // payload/release.json: written by tools/build_site.py from the latest release.
  const release = fetch("payload/release.json", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);

  function formatDate(iso) {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleDateString(lang === "es" ? "es-ES" : "en-GB", { day: "numeric", month: "long", year: "numeric" });
    } catch (e) { return iso.slice(0, 10); }
  }

  function showRelease(info) {
    if (!info) return;
    document.querySelectorAll('[data-release="tag"]').forEach((el) => { el.textContent = info.tag; });
    document.querySelectorAll('[data-release="date"]').forEach((el) => {
      el.textContent = info.publishedAt ? t("rel.published", { date: formatDate(info.publishedAt) }) : "";
    });
    const list = document.querySelector('[data-release="highlights"]');
    if (list && info.highlights) {
      list.replaceChildren(...info.highlights.map((h) => { const li = document.createElement("li"); li.textContent = h; return li; }));
    }
    const notes = document.querySelector('[data-release="notes"]');
    if (notes && info.notesHtml) {
      notes.innerHTML = info.notesHtml;   // made by build_site.py from the release's own notes
      document.querySelector('[data-release="notes-box"]').hidden = false;
    }
    const zip = document.querySelector('[data-release="zip"]');
    if (zip && info.assets && info.assets.windowsZip) zip.href = info.assets.windowsZip;
  }

  window.FR3DS = {
    t, release,
    get lang() { return lang; },
    onLang(fn) { listeners.push(fn); },
  };

  listeners.push(() => release.then(showRelease));
  apply();
})();
