// だれが使っているかを決める。4画面で同じものを読み込む。
//
// 共用のタブレットを想定しているので、開くたびに選び直させない。
// **一度選んだら覚える。** PIN は置かない。
//
// PIN を置かない理由: 守りたいのは「弟が兄のポイントで引き換える」ことだが、
// 引き換えには必ず親の承認が入るのでそこで気づける。
// 毎回 PIN を打たせるコストのほうが、習慣を壊す害が大きい。
//
// 既存の <select id="child"> には触らない。値を入れて change を投げるだけなので、
// 各画面の処理はそのまま動く。切り替えもその select でできる。
(function () {
  // ---------------------------------------------------------------- ログイン（#16）
  //
  // だれが使っているかはログインで決まる。子どものときは:
  //   - 「だれ？」は自分だけ（/api/config が自分だけを返すので、切り替えは出ない）
  //   - 「一覧」（親の画面）への導線と、親だけの操作（.parent-only）を隠す
  // 途中でログインが切れたら（全端末ログアウトなど）、ログイン画面に戻す。
  var root = document.documentElement;
  var style = document.createElement("style");
  style.textContent =
    ':root[data-role="child"] .parent-only,:root[data-role="child"] a[href="/board"]{display:none!important}' +
    // 子どもの端末で親に切り替えているときの帯（#16 ①）。どの画面でも上に出す
    "#who-switched{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:10px;flex-wrap:wrap;" +
    "padding:8px 16px;background:var(--parent-text,#1F2422);color:var(--parent-bg,#fff);font-size:14px}" +
    "#who-switched b{font-weight:700}#who-switched span{flex:1;min-width:12em}" +
    "#who-switched button{font:inherit;font-weight:700;padding:8px 16px;min-height:44px;border-radius:999px;" +
    "border:0;background:var(--parent-bg,#fff);color:var(--parent-text,#1F2422);cursor:pointer}" +
    "#who-switched .who-err{flex-basis:100%;color:var(--parent-bg,#fff);font-weight:700;text-decoration:underline}" +
    // 帯も各画面のヘッダーも sticky で上に付くので、帯の高さだけヘッダーを下げて重ねない（UX_REVIEW PR-17 A3）
    "html[data-who-switched] header{top:var(--who-bar-h,0px)}" +
    "#who-switched button:disabled{opacity:.6;cursor:default}" +
    // 戻れたか分からないとき（R1 追補）。画面全体をおおう
    "#who-unknown{position:fixed;inset:0;z-index:100;display:flex;align-items:center;justify-content:center;" +
    "padding:16px;background:var(--parent-text,#1F2422);color:var(--parent-bg,#fff)}" +
    "#who-unknown>div{max-width:28em;text-align:center}" +
    "#who-unknown p{margin:0 0 12px;font-size:15px;line-height:1.7}" +
    "#who-unknown #who-unknown-t{font-size:18px;font-weight:700}" +
    "#who-unknown button{font:inherit;font-weight:700;margin-top:8px;padding:10px 20px;min-height:44px;" +
    "border-radius:999px;border:0;background:var(--parent-bg,#fff);color:var(--parent-text,#1F2422);cursor:pointer}" +
    "#who-unknown button:disabled{opacity:.6;cursor:default}" +
    "#who-parent{display:block;margin:28px auto 16px;text-align:center;font-size:14px}" +
    // 押せる場所を 44px 以上に（UX_REVIEW R5）
    "#who-parent a{display:inline-flex;align-items:center;min-height:44px;padding:8px 16px;color:inherit;opacity:.8}";
  document.head.appendChild(style);

  var rawFetch = window.fetch.bind(window);
  var leaving = false;
  window.fetch = function () {
    return rawFetch.apply(null, arguments).then(function (res) {
      if (res.status === 401 && !leaving && location.pathname !== "/login") {
        leaving = true;
        if (res.headers.get("X-Mimamori-Reverted")) {
          location.reload();         // 10分操作がなく子どもに戻った。いまの画面を子どもで開き直す
        } else {
          location.href = "/login?next=" + encodeURIComponent(location.pathname);
        }
      }
      return res;
    });
  };

  // ---------------------------------------------------------------- 親に切り替え中（#16 ①）
  //
  // 子どもの端末で親の合言葉を入れると、一時的に親になる。操作が10分なければ子どもに戻す。
  //   - 戻す判断の正本はサーバー（Cookie の期限）。画面は、操作があれば1分おきに期限を延ばし、
  //     操作がないまま10分たったら自分から戻す（画面を開いたまま置いていかれた場合）
  //   - 「子どもに戻す」ボタンは、切り替え中ずっと出す
  var IDLE_MS = 10 * 60 * 1000, TOUCH_MS = 60 * 1000;

  // 「子どもに戻す」。**戻せたのを確かめてから**子どもの画面へ（UX_REVIEW R1）。
  // 戻す操作が失敗したら（通信が切れた・もう戻っていた など）、今の状態を /api/auth/me で確かめて分ける:
  //   - 子どもに戻っている      → 子どもの画面へ
  //   - 401（ログインが切れた） → ログイン画面へ
  //   - まだ親のまま            → 親の帯を残し、やり直せるようにする
  //   - 確かめられない（500・通信断・形式がおかしい）→ 戻れたか分からない。
  //     **親の画面は閉じたまま**「確認できませんでした」と出し、もう一度たしかめられるようにする（R1 追補）
  var backing = false, barBtn = null, barErr = null, unknownBox = null;
  function backToChild(auto) {
    if (backing || leaving) return;
    backing = true;
    var btn = barBtn, err = barErr;
    if (btn) { btn.disabled = true; btn.textContent = "子どもに戻しています…"; }
    if (err) err.textContent = "";
    if (unknownBox) unknownBox.busy(true);
    function fail() {
      backing = false;
      closeUnknown();
      if (btn) { btn.disabled = false; btn.textContent = "子どもに戻す"; }
      if (err) err.textContent = (auto ? "10分たったので子どもに戻そうとしましたが、" : "") +
        "まだ子どもの画面に戻せていません。通信を確認して、もう一度お試しください。";
    }
    function unknown() {
      backing = false;
      if (btn) { btn.disabled = false; btn.textContent = "子どもに戻す"; }
      showUnknown();
    }
    function go() { leaving = true; location.href = "/kid"; }
    function check() {
      return rawFetch("/api/auth/me")
        .then(function (m) {
          if (m.status === 401) return "login";
          if (!m.ok) return null;
          return m.json().then(function (me) {
            if (!me || typeof me !== "object" || typeof me.role !== "string") return null;
            if (me.role === "child" && !me.switched) return "kid";
            if (me.role === "parent" && me.switched) return "parent";
            return null;
          });
        })
        .catch(function () { return null; });
    }
    rawFetch("/api/auth/back", { method: "POST" })
      .then(function (r) { return r.ok ? "kid" : check(); },
            function () { return check(); })
      .then(function (state) {
        if (state === "kid") go();
        else if (state === "login") { leaving = true; location.href = "/login"; }
        else if (state === "parent") fail();
        else unknown();
      });
  }

  // 戻れたか分からないときの幕。画面全体をおおって、親の画面を操作できないようにする
  function showUnknown() {
    if (unknownBox) { unknownBox.busy(false); return; }
    var back = document.createElement("div");
    back.id = "who-unknown";
    back.setAttribute("role", "alertdialog");
    back.setAttribute("aria-modal", "true");
    back.setAttribute("aria-labelledby", "who-unknown-t");
    var box = document.createElement("div");
    var t = document.createElement("p");
    t.id = "who-unknown-t";
    t.textContent = "子どもの画面に 戻せたか、確認できませんでした";
    var d = document.createElement("p");
    d.textContent = "通信を確認して、「もう一度たしかめる」を押してください。確かめられるまで、おうちの人の画面は閉じておきます。";
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = "もう一度たしかめる";
    b.addEventListener("click", function () { backToChild(false); });
    box.appendChild(t); box.appendChild(d); box.appendChild(b);
    back.appendChild(box);
    // 後ろの画面は読み上げ・操作の対象から外す
    var hidden = [];
    Array.prototype.forEach.call(document.body.children, function (el) {
      if (el === back) return;
      hidden.push(el);
      el.setAttribute("aria-hidden", "true");
      el.inert = true;
    });
    document.body.appendChild(back);
    b.focus();
    unknownBox = {
      el: back,
      busy: function (on) {
        b.disabled = on;
        b.textContent = on ? "たしかめています…" : "もう一度たしかめる";
        if (!on) b.focus();
      },
      close: function () {
        hidden.forEach(function (el) { el.removeAttribute("aria-hidden"); el.inert = false; });
        back.remove();
      },
    };
  }
  function closeUnknown() {
    if (!unknownBox) return;
    unknownBox.close();
    unknownBox = null;
  }

  function showSwitched(me) {
    var bar = document.createElement("div");
    bar.id = "who-switched";
    bar.setAttribute("role", "region");
    bar.setAttribute("aria-label", "おうちの人で使っています");
    // HTML は使わずに組み立てる（呼び名は文字として入れる）
    var text = document.createElement("span");
    var who = document.createElement("b"); who.textContent = "おうちの人";
    var kid = document.createElement("b"); kid.textContent = me.back_to;
    text.appendChild(who);
    text.appendChild(document.createTextNode("で つかっています。さわらないと 10分で "));
    text.appendChild(kid);
    text.appendChild(document.createTextNode(" の画面に もどります"));
    barBtn = document.createElement("button");
    barBtn.type = "button"; barBtn.textContent = "子どもに戻す";
    barBtn.addEventListener("click", function () { backToChild(false); });
    barErr = document.createElement("span");
    barErr.className = "who-err"; barErr.setAttribute("role", "alert");
    bar.appendChild(text); bar.appendChild(barBtn); bar.appendChild(barErr);
    document.body.insertBefore(bar, document.body.firstChild);
    root.setAttribute("data-who-switched", "");
    function barHeight() { root.style.setProperty("--who-bar-h", (bar.offsetHeight || 0) + "px"); }
    barHeight();
    if (window.ResizeObserver) new ResizeObserver(barHeight).observe(bar);

    var last = Date.now(), touched = Date.now();
    function active() {
      last = Date.now();
      if (last - touched >= TOUCH_MS) {
        touched = last;
        rawFetch("/api/auth/touch", { method: "POST" }).catch(function () {});
      }
    }
    ["pointerdown", "keydown", "scroll", "touchstart"].forEach(function (ev) {
      window.addEventListener(ev, active, { passive: true, capture: true });
    });
    setInterval(function () {
      if (Date.now() - last >= IDLE_MS) backToChild(true);
    }, 15 * 1000);
  }

  function showParentEntry() {
    // 子どもの画面から親に切り替える入口。見た目の置き場所は塊 A・B（プロフィールのメニュー）で決め直す
    var p = document.createElement("p");
    p.id = "who-parent";
    p.innerHTML = '<a href="/login?switch=parent&next=%2Fboard">おうちの人に かわる</a>';
    document.body.appendChild(p);
  }

  rawFetch("/api/auth/me")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (me) {
      if (!me) return;
      root.dataset.role = me.role;
      // 親子の境界（見た目の色の切り替え）。画面が自分で決めていれば、それに従う
      var aud = root.getAttribute("data-audience");
      if (aud !== "kid" && aud !== "parent") root.setAttribute("data-audience", me.role === "child" ? "kid" : "parent");
      window.mimamoriMe = me;
      var ready = function () {
        if (me.switched) showSwitched(me);
        // 親への入口は、プロフィールのある画面ではその中（appearance.js）。ない画面では下に置く（UX_REVIEW PR-17 A2）
        else if (me.role === "child" && me.auth &&
                 !(window.Appearance && document.querySelector("[data-profile-menu]"))) showParentEntry();
      };
      if (document.body) ready();
      else document.addEventListener("DOMContentLoaded", ready);
      document.dispatchEvent(new CustomEvent("who:me", { detail: me }));
    })
    .catch(function () {});

  var KEY = "mimamori-child";
  // 子どもごとの色。文字で読ませず、色で見分けられるようにする。
  var COLORS = ["#2F6FB5", "#C2614A", "#3F8A6E", "#8A5AA8"];

  function stored() {
    try {
      return localStorage.getItem(KEY) || null;
    } catch (e) {
      return null; // プライベートモードなどで読めないことがある
    }
  }

  function remember(name) {
    try {
      localStorage.setItem(KEY, name);
    } catch (e) {
      // 覚えられなくても、この画面のあいだは選べる
    }
  }

  function colorOf(names, name) {
    var i = names.indexOf(name);
    return COLORS[(i < 0 ? 0 : i) % COLORS.length];
  }

  // select に値を入れて、各画面の change ハンドラを起こす
  function applyTo(select, name) {
    if (!select || select.value === name) return;
    select.value = name;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // 子が決まったことを画面に知らせる。値が変わらなかったとき（覚えていた子が先頭だった等）も出す。
  // 画面は、これを受けてから子ごとの読み込みを始める（決まる前に先頭の子で始めない。#9）
  function ready(select) {
    select.dataset.whoReady = "1";
    select.dispatchEvent(new Event("who:ready"));
  }

  function names(select) {
    return Array.prototype.map.call(select.options, function (o) {
      return o.value || o.textContent;
    });
  }

  // ---------------------------------------------------------------- 選ぶ画面

  function chooser(list, onPick) {
    var back = document.createElement("div");
    back.id = "who-back";
    back.setAttribute("role", "dialog");
    // 親は「どの子のぶんか」を選ぶ（親が子になりかわるわけではない。UX_REVIEW PR-29 A3）
    var q = root.dataset.role === "parent" ? "どの子の ぶんですか？" : "だれが つかう？";
    back.setAttribute("aria-label", q);
    back.innerHTML = '<div id="who-box"><p id="who-q"></p><div id="who-list"></div></div>';
    back.querySelector("#who-q").textContent = q;

    var box = back.querySelector("#who-list");
    list.forEach(function (name) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "who-pick";
      b.style.setProperty("--who-color", colorOf(list, name));
      b.innerHTML =
        '<span class="who-face" aria-hidden="true">' +
        (name.slice(0, 1) || "?") +
        "</span><span>" +
        name +
        "</span>";
      b.addEventListener("click", function () {
        remember(name);
        back.remove();
        onPick(name);
      });
      box.appendChild(b);
    });

    document.body.appendChild(back);
    var first = back.querySelector(".who-pick");
    if (first) first.focus();
  }

  // ---------------------------------------------------------------- 起動

  function start(select) {
    var list = names(select).filter(Boolean);
    if (!list.length) return;

    var saved = stored();
    if (saved && list.indexOf(saved) >= 0) {
      applyTo(select, saved);
      ready(select);
    } else if (list.length === 1) {
      remember(list[0]);
      applyTo(select, list[0]);
      ready(select);
    } else {
      chooser(list, function (name) {
        applyTo(select, name);
        ready(select);
      });
    }

    // 画面の select で切り替えたら、それも覚える
    select.addEventListener("change", function () {
      if (select.value) remember(select.value);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var select = document.getElementById("child");
    if (!select) return;

    if (select.options.length) {
      start(select);
      return;
    }
    // 各画面は /api/config を取ってから select を埋める。埋まるのを待つ。
    var seen = new MutationObserver(function () {
      if (!select.options.length) return;
      seen.disconnect();
      start(select);
    });
    seen.observe(select, { childList: true });
    // 取得に失敗して永遠に埋まらない場合に備えて、監視をやめる
    setTimeout(function () {
      seen.disconnect();
    }, 15000);
  });
})();
