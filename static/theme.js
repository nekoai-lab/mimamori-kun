// 見た目の明暗を選べるようにする。4画面で同じものを読み込む。
//
// OS の設定にそのまま従うと、明るい部屋でも暗いままで読めない。
// 一度選んだら覚える。まだ選んでいないうちは OS に従う。
//
// <head> で同期的に読むこと。描画より先に data-theme を付けないと、
// 明るい設定なのに一瞬だけ暗く光る。
(function () {
  var KEY = "mimamori-theme";
  var root = document.documentElement;

  function stored() {
    try {
      var v = localStorage.getItem(KEY);
      return v === "light" || v === "dark" ? v : null;
    } catch (e) {
      return null; // プライベートモードなどで読めないことがある
    }
  }

  function osTheme() {
    return window.matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light";
  }

  function apply(theme) {
    root.dataset.theme = theme;
    var btn = document.getElementById("theme");
    if (!btn) return;
    var toLight = theme === "dark";
    btn.textContent = toLight ? "☀ 明るく" : "☾ 暗く";
    btn.setAttribute("aria-label", toLight ? "明るい画面にする" : "暗い画面にする");
  }

  apply(stored() || osTheme());

  document.addEventListener("DOMContentLoaded", function () {
    apply(root.dataset.theme);
    var btn = document.getElementById("theme");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var next = root.dataset.theme === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch (e) {
        // 覚えられなくても、この画面のあいだは切り替わる
      }
      apply(next);
    });
  });

  // まだ自分で選んでいないなら、OS の切り替えについていく。
  window.matchMedia("(prefers-color-scheme:dark)").addEventListener("change", function (e) {
    if (!stored()) apply(e.matches ? "dark" : "light");
  });
})();
