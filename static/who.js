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
    } else if (list.length === 1) {
      remember(list[0]);
      applyTo(select, list[0]);
    } else {
      chooser(list, function (name) {
        applyTo(select, name);
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
