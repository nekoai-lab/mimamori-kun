// 見た目の共通基盤（UX 塊 A・design/UX_SPEC.md §3.2〜§3.4・§4.2）
//
// 各画面が本文の最後で読み込む。差込先のある画面だけで動き、ない画面では何もしない。
//   [data-appearance-picker] … 見た目（子どものテーマ）を選ぶ入口とシート
//   [data-family-nav]        … 画面を切り替えるナビ（子：きょう・とる・ごほうび／親：一覧・撮る・ごほうび）
//   [data-profile-menu]      … プロフィール（ログインした子の名前と「おうちの人に かわる」）
//
// 境界（§3.3・§4.2）
//   - 明暗は theme.js（data-theme）。ここでは触らない
//   - 親子は data-audience。子のテーマ（data-kid-theme）は kid のときだけ付ける
//   - 子の正本は各画面の select と who:ready／change。Appearance.setChild(childKey) はテーマだけを変える
//   - 保存は AppearanceStore（テーマ）と CompanionStore（相棒の名前・文体）。同じ子の設定を
//     **部分更新**で書くので、テーマを変えても名前・学年・ふりがなは消えない。その逆も同じ
//   - 設定の口（塊 F）がまだないときは、保存できたふりをしない
(function () {
  if (window.Appearance) return;

  var SCHEMA = 1;
  var ASSET = "/static/assets/appearance/";
  var THEMES = [
    { id: "rocket-lab", name: "ロケットラボ", art: "rocket-lab.svg", stamp: "stamp-rocket-lab.svg" },
    { id: "monochrome", name: "モノクロ", art: "monochrome.svg", stamp: "stamp-monochrome.svg", mono: true },
    { id: "snow-bird", name: "しろい小鳥", art: "snow-bird.svg", stamp: "stamp-snow-bird.svg" },
  ];
  var root = document.documentElement;

  function theme(id) {
    for (var i = 0; i < THEMES.length; i++) if (THEMES[i].id === id) return THEMES[i];
    return null;
  }

  // ---------------------------------------------------------------- 設定の口（塊 F）
  //
  // GET  /api/child-settings?child=<子>        → {settings: {...}, reading_policy: {...}}
  // POST /api/child-settings  {child, ...一部} → {settings: {...}}（送った項目だけを変える）
  // 404・405 は「まだ口がない」。保存できたとは言わない
  var API = "/api/child-settings";

  function unconnected() {
    var e = new Error("unconnected");
    e.unconnected = true;
    return e;
  }

  function call(url, opts) {
    return window.fetch(url, opts).then(function (res) {
      if (res.status === 404 || res.status === 405) throw unconnected();
      if (!res.ok) throw new Error("http " + res.status);
      return res.json();
    }).then(function (body) {
      if (!body || typeof body !== "object" || !body.settings || typeof body.settings !== "object") {
        throw new Error("invalid");
      }
      return body;
    });
  }

  function readAll(child) {
    return call(API + "?child=" + encodeURIComponent(child)).then(function (body) {
      var out = {};
      for (var k in body.settings) out[k] = body.settings[k];
      out.reading_policy = body.reading_policy && typeof body.reading_policy === "object" ? body.reading_policy : {};
      return out;
    });
  }

  function writeSome(child, values, allowed) {
    var body = { child: child };
    allowed.forEach(function (k) { if (values && k in values) body[k] = values[k]; });
    return call(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (res) { return res.settings; });
  }

  window.AppearanceStore = {
    read: function (child) {
      return readAll(child).then(function (s) {
        return { theme_id: s.theme_id, theme_schema_version: s.theme_schema_version };
      });
    },
    write: function (child, values) {
      return writeSome(child, values, ["theme_id", "theme_schema_version"]);
    },
  };
  // 相棒の名前・文体（塊 B が読み書き、塊 G がサーバー側で読む）。テーマとは別の項目として部分更新する
  if (!window.CompanionStore) {
    window.CompanionStore = {
      read: readAll,
      write: function (child, values) {
        return writeSome(child, values, ["companion_name", "companion_language_level"]);
      },
    };
  }

  // 確かめられたテーマだけを、表示を速くするために子ごとに覚える（正本は設定）
  var CACHE = "mimamori-appearance:";
  function cacheGet(child) {
    try { var v = localStorage.getItem(CACHE + child); return theme(v) ? v : null; } catch (e) { return null; }
  }
  function cacheSet(child, id) {
    try { if (id) localStorage.setItem(CACHE + child, id); else localStorage.removeItem(CACHE + child); } catch (e) { /* 覚えられなくても表示はできる */ }
  }

  // ---------------------------------------------------------------- 状態
  var state = {
    child: null,   // いまの子（select の値）
    seq: 0,        // 子を切り替えるたびに増やす。前の子の応答を捨てる
    theme: null,   // この画面で使っているテーマ（null は中立）
    saved: null,   // 設定で確かめられたテーマ
    status: "",    // "" | saving | saved | failed | unconnected
    failed: null,  // 覚えられなかったテーマ（もういちど に使う）
    writeSeq: 0,
    choice: 0,     // 本人がテーマを選ぶたびに増やす。選んだあとに届いた古い設定で戻さない（最後に選んだものが勝つ）
  };

  function audience() {
    var a = root.getAttribute("data-audience") || (document.body && document.body.getAttribute("data-audience"));
    return a === "kid" || a === "parent" ? a : null;
  }

  function paint() {
    if (audience() === "kid" && state.theme) root.setAttribute("data-kid-theme", state.theme);
    else root.removeAttribute("data-kid-theme");
    renderPickers();
  }

  function setChild(child) {
    child = child ? String(child) : null;
    var seq = ++state.seq, choice = state.choice;
    state.child = child;
    state.status = "";
    state.failed = null;
    state.saved = child ? cacheGet(child) : null;
    state.theme = state.saved;     // 取得中は中立か、確かめ済みのキャッシュ
    paint();
    if (!child) return Promise.resolve(null);
    return window.AppearanceStore.read(child).then(function (s) {
      if (seq !== state.seq) return state.theme;           // 別の子に切り替わった
      if (choice !== state.choice) return state.theme;     // 取得中に本人が選んだ。古い設定で戻さない（PR-34 A3）
      var id = s && theme(s.theme_id) ? s.theme_id : null; // 知らない ID は中立（設定は書き換えない）
      state.saved = id;
      state.theme = id;
      cacheSet(child, id);
      paint();
      return id;
    }, function (e) {
      if (seq !== state.seq || choice !== state.choice) return state.theme;
      if (e && e.unconnected) cacheSet(child, null);       // 口がない：確かめられたものはない
      paint();
      return state.theme;
    });
  }

  function commit(id) {
    if (!theme(id) || !state.child) return Promise.resolve(false);
    var child = state.child, seq = state.seq, w = ++state.writeSeq;
    state.choice++;
    state.theme = id;
    state.status = "saving";
    state.failed = null;
    paint();
    return window.AppearanceStore.write(child, { theme_id: id, theme_schema_version: SCHEMA }).then(function () {
      if (seq !== state.seq || w !== state.writeSeq) return false;
      state.saved = id;
      state.status = "saved";
      cacheSet(child, id);
      renderPickers();
      return true;
    }, function () {
      if (seq !== state.seq || w !== state.writeSeq) return false;
      state.status = "failed";   // この画面では変えたけれど、まだ覚えられていない
      state.failed = id;
      renderPickers();
      return false;
    });
  }

  // ---------------------------------------------------------------- 絵
  function art(t, cls, which) {
    var file = ASSET + (which === "stamp" ? t.stamp : t.art);
    var el;
    if (t.mono) {
      // 線画は文字の色で塗る（暗い画面でも見える）
      el = document.createElement("span");
      el.className = cls + " ap-art-mono";
      el.style.setProperty("--ap-mask", 'url("' + file + '")');
    } else {
      el = document.createElement("img");
      el.className = cls;
      el.src = file;
      el.alt = "";
    }
    el.setAttribute("aria-hidden", "true");
    return el;
  }

  function text(tag, cls, value) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = value;
    return el;
  }

  function miniCard(t) {
    var card = document.createElement("span");
    card.className = "ap-mini";
    var stamp = art(t, "ap-stamp", "stamp");
    card.appendChild(stamp);
    card.appendChild(text("span", "", "ドリル"));
    card.appendChild(text("span", "ap-mini-done", "✓ おわった"));
    return card;
  }

  // ---------------------------------------------------------------- 見た目のシート
  var sheet = null, opener = null;

  function buildSheet() {
    var d = document.createElement("dialog");
    d.className = "ap-sheet";
    d.setAttribute("aria-labelledby", "ap-sheet-title");
    var head = document.createElement("div");
    head.className = "ap-sheet-head";
    head.appendChild(text("h2", "", "みためを えらぶ")).id = "ap-sheet-title";
    var close = text("button", "ap-btn", "とじる");
    close.type = "button";
    close.addEventListener("click", function () { closeSheet(); });
    head.appendChild(close);
    var body = document.createElement("div");
    body.className = "ap-sheet-body";
    d.appendChild(head);
    d.appendChild(body);
    d.addEventListener("cancel", function (e) { e.preventDefault(); closeSheet(); });   // Esc
    document.body.appendChild(d);
    // 上に貼り付く見出しの下に、フォーカスした候補が隠れないようにする（文字を大きくしても）
    function pad() { d.style.scrollPaddingTop = (head.offsetHeight + 8) + "px"; }
    if (window.ResizeObserver) new ResizeObserver(pad).observe(head);
    pad();
    return { el: d, body: body };
  }

  function showList(focusId) {
    var body = sheet.body;
    body.replaceChildren();
    body.appendChild(text("p", "ap-muted", "なまえ・かいわ・だいしは そのままで、みためだけが かわるよ。"));
    var list = document.createElement("ul");
    list.className = "ap-choices";
    var focus = null;
    THEMES.forEach(function (t) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "ap-choice";
      b.setAttribute("data-kid-theme", t.id);
      var picked = state.theme === t.id;
      b.setAttribute("aria-pressed", picked ? "true" : "false");
      b.appendChild(art(t, "ap-art", "art"));
      var info = document.createElement("span");
      info.className = "ap-info";
      info.appendChild(text("span", "ap-name", t.name));
      if (picked) info.appendChild(text("span", "ap-picked", "えらんでいる"));
      info.appendChild(miniCard(t));
      b.appendChild(info);
      b.addEventListener("click", function () { showPreview(t); });
      li.appendChild(b);
      list.appendChild(li);
      if (t.id === (focusId || state.theme)) focus = b;
    });
    body.appendChild(list);
    (focus || list.querySelector("button")).focus();
  }

  function showPreview(t) {
    var body = sheet.body;
    body.replaceChildren();
    var box = document.createElement("div");
    box.className = "ap-preview";
    box.setAttribute("data-kid-theme", t.id);
    box.appendChild(art(t, "ap-art", "art"));
    var title = text("p", "", t.name + "で ためしてみる");
    title.style.fontWeight = "700";
    title.style.margin = "0";
    title.tabIndex = -1;
    box.appendChild(title);
    var card = document.createElement("div");
    card.className = "ap-card";
    card.appendChild(art(t, "ap-stamp", "stamp"));
    card.appendChild(text("span", "ap-card-name", "きょうの ドリル"));
    card.appendChild(text("span", "ap-go", "おわった"));
    box.appendChild(card);
    box.appendChild(text("p", "ap-muted", "これは みほん。まだ かわっていないよ。"));
    body.appendChild(box);
    var actions = document.createElement("div");
    actions.className = "ap-actions";
    var ok = text("button", "ap-btn ap-primary", "これにする");
    ok.type = "button";
    ok.addEventListener("click", function () { closeSheet(); commit(t.id); });
    var back = text("button", "ap-btn", "やめる");
    back.type = "button";
    back.addEventListener("click", function () { showList(t.id); });
    actions.appendChild(ok);
    actions.appendChild(back);
    body.appendChild(actions);
    title.focus();
  }

  function openSheet(from) {
    if (!sheet) sheet = buildSheet();
    opener = from || null;
    if (typeof sheet.el.showModal === "function") { if (!sheet.el.open) sheet.el.showModal(); }
    else sheet.el.setAttribute("open", "");
    showList();
  }

  function closeSheet() {
    if (!sheet) return;
    if (typeof sheet.el.close === "function" && sheet.el.open) sheet.el.close();
    else sheet.el.removeAttribute("open");
    if (opener && opener.isConnected) opener.focus();   // 入口へ戻す
  }

  // ---------------------------------------------------------------- 入口（[data-appearance-picker]）
  var STATUS = {
    saving: "おぼえているところ…",
    saved: "このみためを おぼえたよ",
    failed: "この画面では変えたけれど、まだ覚えられていないよ",
  };

  function renderPickers() {
    var who = audience();
    document.querySelectorAll("[data-appearance-picker]").forEach(function (slot) {
      if (who === "parent") {        // 親の画面は子のテーマを持たない
        slot.hidden = true;
        return;
      }
      if (who !== "kid" || !state.child) return;   // 決まるまでは各画面のまま
      slot.hidden = false;
      var btn = slot.querySelector(".ap-open"), status = slot.querySelector(".ap-status");
      if (!btn) {
        slot.replaceChildren();
        btn = text("button", "ap-open", "みため");
        btn.type = "button";
        btn.setAttribute("aria-haspopup", "dialog");
        btn.addEventListener("click", function () { openSheet(btn); });
        // 状態の欄は作り直さない（押したボタンが消えてフォーカスが外れないように。PR-34 A2）
        status = document.createElement("span");
        status.className = "ap-status";
        status.setAttribute("role", "status");
        var msg = text("span", "ap-status-text", "");
        msg.tabIndex = -1;
        var again = text("button", "ap-retry", "もういちど");
        again.type = "button";
        again.hidden = true;
        again.addEventListener("click", function () { retry(slot); });
        status.appendChild(msg);
        status.appendChild(again);
        slot.appendChild(btn);
        slot.appendChild(status);
      }
      var t = theme(state.theme);
      btn.setAttribute("aria-label", "みため（いまは " + (t ? t.name : "ふつう") + "）");
      status.querySelector(".ap-status-text").textContent = STATUS[state.status] || "";
      status.querySelector(".ap-retry").hidden = state.status !== "failed";
      status.hidden = !STATUS[state.status];
    });
  }

  // 「もういちど」：待っているあいだは結果の文言に、再失敗なら新しい「もういちど」に、
  // 覚えられたら結果の文言にフォーカスを置く。待っているあいだに別の操作へ移ったら奪わない
  function retry(slot) {
    var msg = slot.querySelector(".ap-status-text"), again = slot.querySelector(".ap-retry");
    msg.focus();
    commit(state.failed).then(function () {
      var here = document.activeElement;
      if (here !== msg && here !== again && here !== document.body && here !== null) return;
      if (state.status === "failed" && !again.hidden) again.focus();
      else msg.focus();
    });
  }

  // ---------------------------------------------------------------- ナビ（[data-family-nav]）
  var NAV = {
    kid: [["きょう", "/kid"], ["とる", "/?mode=kid"], ["ごほうび", "/reward"]],
    parent: [["一覧", "/board"], ["撮る", "/?mode=parent"], ["ごほうび", "/reward?view=parent"]],
  };
  function pathOf(href) {
    try { return new URL(href, location.href).pathname; } catch (e) { return href; }
  }

  function renderNavs() {
    var who = audience();
    if (!who) return;
    var here = location.pathname;
    var canon = {};
    NAV.kid.concat(NAV.parent).forEach(function (n) { canon[pathOf(n[1])] = true; });
    document.querySelectorAll("[data-family-nav]").forEach(function (nav) {
      nav.querySelectorAll("a[data-ap-nav]").forEach(function (a) { a.remove(); });
      // 各画面の元のリンク：重なるもの、子のときは親向けのものを隠す（消さない。A がなくても動くように）
      nav.querySelectorAll("a").forEach(function (a) {
        var hide = canon[pathOf(a.getAttribute("href") || "")] || who === "kid";
        if (hide) { a.hidden = true; a.setAttribute("data-ap-hidden", ""); }
        else if (a.hasAttribute("data-ap-hidden")) { a.hidden = false; a.removeAttribute("data-ap-hidden"); }
      });
      var first = nav.firstChild;
      NAV[who].forEach(function (n) {
        var a = text("a", "ap-nav-link", n[0]);
        a.href = n[1];
        a.setAttribute("data-ap-nav", "");
        if (pathOf(n[1]) === here) a.setAttribute("aria-current", "page");
        nav.insertBefore(a, first);
      });
      nav.classList.add("ap-nav");
    });
  }

  // ---------------------------------------------------------------- プロフィール（[data-profile-menu]）
  function renderProfiles() {
    var me = window.mimamoriMe;
    if (!me || me.role !== "child" || me.switched) return;   // 親・切り替え中は帯（who.js）が受け持つ
    document.querySelectorAll("[data-profile-menu]").forEach(function (slot) {
      var details = slot.tagName === "DETAILS" ? slot : slot.querySelector("details.ap-profile");
      if (!details) {
        details = document.createElement("details");
        slot.replaceChildren(details);
      }
      details.classList.add("ap-profile");
      var summary = details.querySelector("summary");
      if (!summary) { summary = document.createElement("summary"); details.insertBefore(summary, details.firstChild); }
      summary.textContent = me.name || me.user || "わたし";
      summary.setAttribute("aria-label", (me.name || "わたし") + " のメニュー");
      Array.prototype.slice.call(details.children).forEach(function (el) { if (el !== summary) el.remove(); });
      var menu = document.createElement("div");
      menu.className = "ap-profile-menu";
      if (me.auth) {
        var a = text("a", "", "おうちの人に かわる");
        a.href = "/login?switch=parent&next=%2Fboard";
        menu.appendChild(a);
      }
      details.appendChild(menu);
    });
  }

  // ---------------------------------------------------------------- 起動
  function refresh() {
    paint();
    renderNavs();
    renderProfiles();
  }

  window.Appearance = {
    themes: THEMES.map(function (t) { return { id: t.id, name: t.name }; }),
    setChild: setChild,
    current: function () { return { child: state.child, theme: state.theme, saved: state.saved, status: state.status }; },
    open: function () { openSheet(null); },
    refresh: refresh,
    _commit: commit,
  };

  // 親子が決まった・変わったら塗り直す（各画面が data-audience を付ける）
  if (window.MutationObserver) {
    var watch = new MutationObserver(refresh);
    watch.observe(root, { attributes: true, attributeFilter: ["data-audience"] });
    if (document.body) watch.observe(document.body, { attributes: true, attributeFilter: ["data-audience"] });
  }
  document.addEventListener("who:me", refresh);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", refresh);
  else refresh();
})();
