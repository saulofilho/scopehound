"use strict";
(function () {
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // O faro percorre a trilha até a cerca do escopo.
  var path = document.getElementById("scent");
  var runner = document.querySelector(".runner");
  if (path && runner) {
    var total = path.getTotalLength();
    var place = function (t) {
      var p = path.getPointAtLength(t * total);
      runner.setAttribute("cx", p.x);
      runner.setAttribute("cy", p.y);
    };
    if (reduced) {
      place(1);
    } else {
      var duration = 5200;
      var start = null;
      var step = function (now) {
        if (start === null) start = now;
        var t = ((now - start) % duration) / duration;
        var eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        place(eased);
        requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }
  }

  // Borda da navegação ao rolar.
  var nav = document.querySelector(".nav");
  var onScroll = function () {
    if (nav) nav.classList.toggle("scrolled", window.scrollY > 8);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // Seções aparecem ao entrar na tela.
  var targets = document.querySelectorAll(".section-head, .flow, .guardrail-strip, .card, .terminal, .col, .steps, .start-cta");
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

  // Copiar o comando de instalação.
  document.querySelectorAll("[data-copy]").forEach(function (el) {
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "0");
    el.setAttribute("aria-label", "Copiar: " + el.dataset.copy);
    var copy = function () {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(el.dataset.copy).then(function () {
        var label = el.querySelector(".copy");
        el.classList.add("copied");
        if (label) label.textContent = "copiado";
        setTimeout(function () {
          el.classList.remove("copied");
          if (label) label.textContent = "copiar";
        }, 1600);
      });
    };
    el.addEventListener("click", copy);
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copy(); }
    });
  });
})();
