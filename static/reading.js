// 学年に合わせた漢字・ふりがな（UX_SPEC §3.7・塊 H・#26）。
//
// 漢字を避けきらず、読める形で出会えるようにする。画面に出す文字だけを変え、元のデータは変えない。
//
//   - 字表：文部科学省「学年別漢字配当表」（平成29年告示）。data/reading/kanji-grades.json
//   - 語の辞書：data/reading/words.json（語単位の読み。レビュー済みのものだけを置く）
//   - 固定ラベル：data/reading/labels.json（「きょう／今日」など）
//
// 決め方：
//   - 知っている字だけの語は、そのまま漢字
//   - 辞書にある語で、知らない字を含むものは、漢字＋ふりがな
//   - 辞書にない語で、知らない字を含むものは、**原文のまま**（読みを推測で付けない）。unresolved に入れて返す
//   - 「今日」のように字から読みが出ない語（irregular）は、小学生では字を知っていてもふりがなを外さない
//   - 問題の本文（contentRole: "question"）には、ふりがなを付けない（答えを漏らさない）
//
// **HTML は作らない・受け取らない。** DOM は createElement とテキストだけで組み立てる。
//
// policy（塊 F の子ごとの設定）:
//   school_grade          "e1"〜"e6"（小1〜小6）、"j1"〜"j3"（中1〜中3）、null（未設定）
//   kanji_scope           "previous_grade"（既定。前の学年まで）／"current_grade"（この学年まで）
//   ruby_mode             "auto"（既定）／"all"（辞書にある語すべてに読み）
//   known_kanji_overrides ["字", …]  習った字を足す
//   ruby_word_overrides   ["語", …]  範囲内でも読みを付ける語
(function (root) {
  "use strict";

  var data = { grades: null, words: null, labels: null };
  var gradeOf = {};          // 字 → 1〜6
  var wordList = [];         // 長い順（最長一致のため）
  var ready = false;

  var KANJI = /[㐀-䶿一-鿿豈-﫿々]/;   // 々 も漢字の並びに含める

  function isKanji(ch) { return KANJI.test(ch); }

  function setData(grades, words, labels) {
    data.grades = grades || null;
    data.words = words || null;
    data.labels = labels || null;
    gradeOf = {};
    if (grades && grades.grades) {
      Object.keys(grades.grades).forEach(function (g) {
        Array.from(grades.grades[g]).forEach(function (ch) { gradeOf[ch] = Number(g); });
      });
    }
    wordList = words && words.words ? Object.keys(words.words).sort(function (a, b) {
      return b.length - a.length;
    }) : [];
    ready = !!(grades && words);
  }

  function load(base) {
    base = base || "/static/data/reading/";
    function get(name) {
      return fetch(base + name).then(function (r) {
        if (!r.ok) throw new Error(name + " " + r.status);
        return r.json();
      });
    }
    return Promise.all([get("kanji-grades.json"), get("words.json"), get("labels.json").catch(function () { return null; })])
      .then(function (all) { setData(all[0], all[1], all[2]); return true; })
      .catch(function () { setData(null, null, null); return false; });   // 取れなければ原文のまま出す
  }

  // ---------------------------------------------------------------- 知っている字

  function level(policy) {
    var g = policy && policy.school_grade;
    if (!g) return null;
    var m = /^([ej])([1-9])$/.exec(String(g));
    if (!m) return null;
    return m[1] === "e" ? { school: "e", n: Number(m[2]) } : { school: "j", n: Number(m[2]) };
  }

  function knows(ch, policy, lv) {
    var extra = (policy && policy.known_kanji_overrides) || [];
    if (extra.indexOf(ch) >= 0) return true;
    if (!lv) return false;                           // 未設定：基本語に読みを添える中立表示
    var g = gradeOf[ch];
    if (lv.school === "j") return !!g;               // 中学生：小学校の字は通常の漢字
    if (!g) return false;
    var scope = (policy && policy.kanji_scope) === "current_grade" ? lv.n : lv.n - 1;
    return g <= scope;
  }

  // ---------------------------------------------------------------- 読みの割り当て

  // 送り仮名・前の仮名を、読みの中から取り除いて、漢字の並びごとの読みに分ける。
  // 例：「見た目」「みため」→ [見:み][た][目:め]。合わなければ null（読みを付けない）
  function align(word, reading) {
    var parts = [], re = "^", i = 0;
    while (i < word.length) {
      var kan = isKanji(word[i]), j = i;
      while (j < word.length && isKanji(word[j]) === kan) j++;
      parts.push({ text: word.slice(i, j), kanji: kan });
      re += kan ? "(.+?)" : word.slice(i, j).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      i = j;
    }
    var m = new RegExp(re + "$").exec(reading);
    if (!m) return null;
    var k = 1;
    return parts.map(function (p) { return p.kanji ? { text: p.text, ruby: m[k++] } : { text: p.text }; });
  }

  // 文を区切る。返り：[{text, ruby?, word?, unresolved?}]
  function segments(text, policy, opts) {
    text = String(text == null ? "" : text);
    opts = opts || {};
    policy = policy || {};
    if (opts.contentRole === "question") return [{ text: text }];      // 問題には読みを付けない
    if (!ready) return runsOnly(text, true);
    var lv = level(policy);
    var all = policy.ruby_mode === "all" || !!opts.readingsOn;
    var forced = policy.ruby_word_overrides || [];
    var out = [], i = 0;
    while (i < text.length) {
      var w = match(text, i);
      if (w) {
        var info = data.words.words[w];
        var kanjiChars = Array.from(w).filter(isKanji);
        var known = kanjiChars.every(function (ch) { return knows(ch, policy, lv); });
        var irregular = !!info.irregular && (!lv || lv.school === "e");
        var need = all || !lv || !known || irregular || forced.indexOf(w) >= 0;
        var pieces = need ? align(w, info.r) : null;
        if (pieces) {
          pieces.forEach(function (p) { out.push(p.ruby ? { text: p.text, ruby: p.ruby, word: w } : { text: p.text, word: w }); });
        } else {
          out.push({ text: w, word: w });
        }
        i += w.length;
        continue;
      }
      // 辞書にない漢字の並び
      if (isKanji(text[i])) {
        var j = i;
        while (j < text.length && isKanji(text[j]) && !match(text, j)) j++;
        var run = text.slice(i, j);
        var ok = Array.from(run).every(function (ch) { return knows(ch, policy, lv); });
        out.push(ok && lv ? { text: run } : { text: run, unresolved: true });
        i = j;
        continue;
      }
      var k = i;
      while (k < text.length && !isKanji(text[k]) && !match(text, k)) k++;
      out.push({ text: text.slice(i, k) });
      i = k;
    }
    return merge(out);
  }

  function runsOnly(text, flag) {
    var out = [], i = 0;
    while (i < text.length) {
      var kan = isKanji(text[i]), j = i;
      while (j < text.length && isKanji(text[j]) === kan) j++;
      out.push(kan && flag ? { text: text.slice(i, j), unresolved: true } : { text: text.slice(i, j) });
      i = j;
    }
    return out;
  }

  function match(text, i) {
    for (var n = 0; n < wordList.length; n++) {
      var w = wordList[n];
      if (text.substr(i, w.length) === w) return w;
    }
    return null;
  }

  function merge(segs) {
    var out = [];
    segs.forEach(function (s) {
      var last = out[out.length - 1];
      if (last && !last.ruby && !s.ruby && !last.unresolved && !s.unresolved) last.text += s.text;
      else out.push({ text: s.text, ruby: s.ruby, unresolved: s.unresolved });
    });
    return out;
  }

  // ---------------------------------------------------------------- 描く

  // 返り：{ node: DocumentFragment, speech: 読み上げ用の文（原文）, unresolved: [読みの確認が要る語] }
  function render(text, policy, opts, doc) {
    doc = doc || root.document;
    var segs = segments(text, policy, opts);
    var frag = doc.createDocumentFragment();
    segs.forEach(function (s) {
      if (!s.ruby) { frag.appendChild(doc.createTextNode(s.text)); return; }
      var ruby = doc.createElement("ruby");
      ruby.appendChild(doc.createTextNode(s.text));
      var open = doc.createElement("rp"); open.appendChild(doc.createTextNode("（")); open.setAttribute("aria-hidden", "true");
      var rt = doc.createElement("rt"); rt.appendChild(doc.createTextNode(s.ruby)); rt.setAttribute("aria-hidden", "true");
      var close = doc.createElement("rp"); close.appendChild(doc.createTextNode("）")); close.setAttribute("aria-hidden", "true");
      ruby.appendChild(open); ruby.appendChild(rt); ruby.appendChild(close);
      frag.appendChild(ruby);
    });
    return {
      node: frag,
      speech: String(text == null ? "" : text),     // 本文とふりがなを二重に読ませない
      unresolved: segs.filter(function (s) { return s.unresolved; }).map(function (s) { return s.text; }),
    };
  }

  // 固定ラベル（ナビ・ボタン）。読みの要る字を含むなら、ふりがなではなく「かな」で出す（短いラベルに読みは窮屈なため）
  function label(key, policy) {
    var l = data.labels && data.labels.labels && data.labels.labels[key];
    if (!l) return null;
    if (!ready) return l.kana;
    var segs = segments(l.text, policy, {});
    var plain = segs.every(function (s) { return !s.ruby && !s.unresolved; });
    return plain ? l.text : l.kana;
  }

  var api = {
    load: load, setData: setData, segments: segments, render: render, label: label,
    get ready() { return ready; },
  };
  root.Reading = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
