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
    ':root[data-role="child"] .parent-only,:root[data-role="child"] a[href="/board"]{display:none!important}';
  document.head.appendChild(style);

  var rawFetch = window.fetch.bind(window);
  var leaving = false;
  window.fetch = function () {
    return rawFetch.apply(null, arguments).then(function (res) {
      if (res.status === 401 && !leaving && location.pathname !== "/login") {
        leaving = true;
        location.href = "/login?next=" + encodeURIComponent(location.pathname);
      }
      return res;
    });
  };

  rawFetch("/api/auth/me")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (me) {
      if (!me) return;
      root.dataset.role = me.role;
      window.mimamoriMe = me;
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
    back.setAttribute("aria-label", "だれが つかう？");
    back.innerHTML =
      '<div id="who-box"><p id="who-q">だれが つかう？</p><div id="who-list"></div></div>';

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
