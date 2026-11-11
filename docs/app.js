"use strict";
(function () {
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- ícones em pixel (1 bit) ----------
  var PX = {
    hound: [
      "......................X.",
      ".....................X..",
      ".....................X..",
      "........XXXXXXXXXXXXXX..",
      "...XX..XXXXXXXXXXXXXXX..",
      "..XXXXXXXXXXXXXXXXXXXX..",
      ".XX.XXXXXXXXXXXXXXXXXX..",
      ".XXXXX.XXXXXXXXXXXXXXX..",
      "XXXXXX.XXXXXXXXXXXXXX...",
      "XX..XX..X.X.......X.X...",
      "....XX..X.X.......X.X...",
      "........X.X.......X.X...",
      ".......XX.XX.....XX.XX.."
    ],
    computer: [
      "................",
      ".XXXXXXXXXXXXXX.",
      ".X............X.",
      ".X.XXXXXXXXXX.X.",
      ".X.X........X.X.",
      ".X.X.X......X.X.",
      ".X.X........X.X.",
      ".X.XXXXXXXXXX.X.",
      ".X............X.",
      ".XXXXXXXXXXXXXX.",
      "......XXXX......",
      "....XXXXXXXX....",
      "...X........X...",
      "...XXXXXXXXXX...",
      "................",
      "................"
    ],
    folder: [
      "................",
      "................",
      ".XXXXX..........",
      ".X...XXXXXXXXX..",
      ".X...........X..",
      ".XXXXXXXXXXXXXX.",
      ".X............X.",
      ".X............X.",
      ".X............X.",
      ".X............X.",
      ".X............X.",
      ".X............X.",
      ".XXXXXXXXXXXXXX.",
      "................",
      "................",
      "................"
    ],
    bin: [
      "................",
      "......XXXX......",
      "..XXXXXXXXXXXX..",
      "................",
      "...XXXXXXXXXX...",
      "...X.X.XX.X.X...",
      "...X.X.XX.X.X...",
      "...X.X.XX.X.X...",
      "...X.X.XX.X.X...",
      "...X.X.XX.X.X...",
      "...X.X.XX.X.X...",
      "...X.X.XX.X.X...",
      "....XXXXXXXX....",
      "................",
      "................",
      "................"
    ],
    warn: [
      ".......XX.......",
      "......XXXX......",
      "......X..X......",
      ".....XX..XX.....",
      ".....X.XX.X.....",
      "....XX.XX.XX....",
      "....X..XX..X....",
      "...XX..XX..XX...",
      "...X...XX...X...",
      "..XX...XX...XX..",
      "..X..........X..",
      ".XX....XX....XX.",
      ".X.....XX.....X.",
      "XXXXXXXXXXXXXXXX",
      "................",
      "................"
    ],
    lock: [
      "................",
      ".....XXXXXX.....",
      "....XX....XX....",
      "....X......X....",
      "....X......X....",
      "....X......X....",
      "..XXXXXXXXXXXX..",
      "..X..........X..",
      "..X....XX....X..",
      "..X...XXXX...X..",
      "..X....XX....X..",
      "..X....XX....X..",
      "..X..........X..",
      "..XXXXXXXXXXXX..",
      "................",
      "................"
    ],
    book: [
      "................",
      ".XXXXXX..XXXXXX.",
      ".X.....XX.....X.",
      ".X.XXX.XX.XXX.X.",
      ".X.....XX.....X.",
      ".X.XXX.XX.XXX.X.",
      ".X.....XX.....X.",
      ".X.XXX.XX.XXX.X.",
      ".X.....XX.....X.",
      ".X.XX..XX.XX..X.",
      ".X.....XX.....X.",
      ".XXXXXXXXXXXXXX.",
      "...............",
      "................",
      "................",
      "................"
    ],
    lens: [
      "................",
      "....XXXXX.......",
      "...X.....X......",
      "..X.......X.....",
      "..X.XX....X.....",
      "..X.X.....X.....",
      "..X.......X.....",
      "..X.......X.....",
      "...X.....X......",
      "....XXXXXXX.....",
      "..........XX....",
      "...........XX...",
      "............XX..",
      ".............XX.",
      "..............X.",
      "................"
    ],
    check: [
      "................",
      ".XXXXXXXXXXXXXX.",
      ".XXXXXXXXXXXXXX.",
      ".X............X.",
      ".X..........X.X.",
      ".X.........XX.X.",
      ".X........XX..X.",
      ".X..X....XX...X.",
      ".X..XX..XX....X.",
      ".X...XXXX.....X.",
      ".X....XX......X.",
      ".X............X.",
      ".XXXXXXXXXXXXXX.",
      "................",
      "................",
      "................"
    ],
    target: [
      "................",
      ".....XXXXXX.....",
      "...XX......XX...",
      "..X...XXXX...X..",
      "..X..X....X..X..",
      ".X..X..XX..X..X.",
      ".X..X.XXXX.X..X.",
      ".X..X.XXXX.X..X.",
      ".X..X..XX..X..X.",
      "..X..X....X..X..",
      "..X...XXXX...X..",
      "...XX......XX...",
      ".....XXXXXX.....",
      "................",
      "................",
      "................"
    ],
    spark: [
      "...X...",
      "...X...",
      "...X...",
      "XXX.XXX",
      "...X...",
      "...X...",
      "...X..."
    ]
  };

  function pixelSvg(rows) {
    var h = rows.length, w = 0, d = "";
    rows.forEach(function (row, y) {
      w = Math.max(w, row.length);
      var x = 0;
      while (x < row.length) {
        if (row[x] === "X") {
          var start = x;
          while (row[x] === "X") x++;
          d += "M" + start + " " + y + "h" + (x - start) + "v1h-" + (x - start) + "z";
        } else {
          x++;
        }
      }
    });
    return '<svg viewBox="0 0 ' + w + " " + h + '" shape-rendering="crispEdges" preserveAspectRatio="xMidYMid meet" aria-hidden="true"><path fill="currentColor" d="' + d + '"/></svg>';
  }
  document.querySelectorAll("[data-px]").forEach(function (el) {
    var rows = PX[el.dataset.px];
    if (rows) el.innerHTML = pixelSvg(rows);
  });

  // ---------- estrelas em cruz no céu do hero ----------
  var hero = document.querySelector(".hero");
  if (hero) {
    [[7, 12], [90, 8], [93, 36], [4, 48], [96, 64], [3, 78]].forEach(function (p) {
      var s = document.createElement("i");
      s.className = "sparkle";
      s.setAttribute("aria-hidden", "true");
      s.style.left = p[0] + "%";
      s.style.top = p[1] + "%";
      s.innerHTML = pixelSvg(PX.spark);
      hero.appendChild(s);
    });
  }

  // ---------- relógio da barra de tarefas ----------
  function tick() {
    var d = new Date();
    var t = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    ["clock", "clock2"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.textContent = t;
    });
  }
  tick();
  setInterval(tick, 15000);

  // ---------- sessão animada no monitor ----------
  var term = document.getElementById("term");
  var dialog = document.getElementById("dialog");
  var approve = document.getElementById("approve");
  var leads = document.getElementById("leads");
  var SCRIPT = [
    ["C:\\LAB> scopehound chat lab", "dim"],
    ["você › mapeie a API e procure IDOR", ""],
    ["scopehound › site map: 14 endpoints, 3 com {id}", ""],
    ["  ↳ site_map()", "dim"],
    ["  ↳ replay_as GET /rest/basket/6 como userB", "dim"],
    ["scopehound › userB leu a cesta de userA.", ""],
    ["  ↳ send_request PUT /api/BasketItems/7", "dim"],
    ["@dialog"],
    ["  ✓ aprovado uma vez · 200 OK", "dim"],
    ["  ↳ verify_finding GET /rest/basket/6", "dim"],
    ["@verified"]
  ];
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  function line(text, cls) {
    var span = document.createElement("span");
    if (cls) span.className = cls;
    term.insertBefore(span, term.querySelector(".cur"));
    term.insertBefore(document.createTextNode("\n"), term.querySelector(".cur"));
    return span;
  }
  async function typeLine(text, cls) {
    var span = line("", cls);
    for (var i = 0; i < text.length; i++) {
      span.textContent += text[i];
      await sleep(text[i] === " " ? 8 : 22);
    }
    await sleep(260);
  }
  function addLead() {
    var li = document.createElement("li");
    li.className = "new";
    li.innerHTML = "<b>[HIGH]</b> IDOR /rest/basket/{id}";
    leads.insertBefore(li, leads.firstChild);
  }
  function resetScreen() {
    term.innerHTML = '<span class="cur"></span>';
    var fresh = leads.querySelector(".new");
    if (fresh) fresh.remove();
    dialog.hidden = true;
    approve.classList.remove("pressed");
  }
  async function runSession() {
    for (;;) {
      resetScreen();
      for (var i = 0; i < SCRIPT.length; i++) {
        var step = SCRIPT[i];
        if (step[0] === "@dialog") {
          await sleep(300);
          dialog.hidden = false;
          await sleep(1900);
          approve.classList.add("pressed");
          await sleep(260);
          dialog.hidden = true;
          approve.classList.remove("pressed");
        } else if (step[0] === "@verified") {
          var v = line("", "inv");
          v.textContent = " VERIFICADO  IDOR em /rest/basket/{id}  [HIGH] ";
          addLead();
          await sleep(4200);
        } else {
          await typeLine(step[0], step[1]);
        }
      }
    }
  }
  if (term && dialog && leads) {
    if (reduced) {
      resetScreen();
      SCRIPT.forEach(function (s) {
        if (s[0] === "@verified") {
          line("", "inv").textContent = " VERIFICADO  IDOR em /rest/basket/{id}  [HIGH] ";
          addLead();
        } else if (s[0][0] !== "@") {
          line("", s[1]).textContent = s[0];
        }
      });
    } else {
      runSession();
    }
  }

  // ---------- o farejador dentro da cerca ----------
  var yard = document.querySelector(".yard");
  var hound = document.getElementById("hound");
  var trail = document.getElementById("trail");
  if (yard && hound && trail) {
    var pos = 0.08, dir = 1;
    var draw = function () {
      var W = yard.clientWidth, hw = hound.clientWidth, margin = W * 0.025;
      var min = margin, max = W - hw - margin;
      var x = min + (max - min) * pos;
      hound.style.left = x + "px";
      hound.classList.toggle("flip", dir > 0); // o sprite olha para a esquerda
      if (dir > 0) {
        trail.style.left = min + "px";
        trail.style.width = Math.max(0, x - min) + "px";
      } else {
        trail.style.left = (x + hw) + "px";
        trail.style.width = Math.max(0, max + hw - (x + hw)) + "px";
      }
    };
    draw();
    window.addEventListener("resize", draw);
    if (!reduced) {
      setInterval(function () {
        pos += dir * 0.012;
        if (pos >= 1) { pos = 1; dir = -1; }
        if (pos <= 0) { pos = 0; dir = 1; }
        draw();
      }, 90);
    }
  }

  // ---------- copiar o comando ----------
  document.querySelectorAll("[data-copy]").forEach(function (el) {
    var copy = function () {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(el.dataset.copy).then(function () {
        el.classList.add("copied");
        setTimeout(function () { el.classList.remove("copied"); }, 1600);
      });
    };
    el.addEventListener("click", copy);
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copy(); }
    });
  });

  // ---------- janelas aparecem ao rolar ----------
  var targets = document.querySelectorAll(".sec-head, .sec .win, .pair");
  if (!reduced && "IntersectionObserver" in window) {
    targets.forEach(function (el) { el.classList.add("reveal"); });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    targets.forEach(function (el) { io.observe(el); });
  }
})();
