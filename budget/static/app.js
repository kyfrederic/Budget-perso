/* Mouvement et petites interactions. Amélioration progressive :
   sans ce fichier, chaque page est complète et utilisable. */
(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var ease = function (p) { return 1 - Math.pow(1 - p, 4); };

  function animate(duration, delay, step, done) {
    var start = null;
    function frame(t) {
      if (start === null) start = t + delay;
      var p = Math.min(1, Math.max(0, (t - start) / duration));
      step(ease(p));
      if (p < 1) requestAnimationFrame(frame); else if (done) done();
    }
    requestAnimationFrame(frame);
  }

  // Chiffres qui montent. Le texte final est celui rendu par le serveur.
  function countUp(el) {
    var cents = parseInt(el.dataset.count, 10), final = el.textContent;
    if (reduce || !isFinite(cents) || Math.abs(cents) < 100) return;
    var fmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
    animate(1200, 0, function (e) {
      var v = Math.round(cents * e / 100);
      el.textContent = (v < 0 ? '−' : '') + fmt.format(Math.abs(v)) + ' €';
    }, function () { el.textContent = final; });
  }

  // Anneau du matelas : part de vide, rejoint la valeur rendue par le serveur.
  function fillRing(c) {
    if (reduce) return;
    var target = c.getAttribute('stroke-dashoffset'), full = c.getAttribute('stroke-dasharray');
    c.style.transition = 'none'; c.style.strokeDashoffset = full;
    c.getBoundingClientRect();
    requestAnimationFrame(function () { c.style.transition = ''; c.style.strokeDashoffset = target; });
  }

  // Barres d'avancement qui se remplissent l'une après l'autre.
  function fillBar(bar, i) {
    var target = bar.value;
    if (reduce || !target) return;
    bar.value = 0;
    animate(900, 200 + i * 90, function (e) { bar.value = target * e; }, function () { bar.value = target; });
  }

  // Virements : cocher sans recharger la page.
  function wireTransfer(form) {
    form.addEventListener('submit', function (ev) {
      if (!window.fetch) return;
      ev.preventDefault();
      var btn = form.querySelector('button'), li = form.closest('li');
      fetch(form.action, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          btn.setAttribute('aria-pressed', d.done ? 'true' : 'false');
          li.classList.toggle('done', d.done);
          var left = document.querySelectorAll('.virements li:not(.later) .check-btn[aria-pressed="false"]').length;
          var out = document.querySelector('[data-left]');
          if (out) out.textContent = left ? left + ' à faire' : 'tous faits';
        })
        .catch(function () { form.submit(); });
    });
  }

  document.querySelectorAll('[data-count]').forEach(countUp);
  document.querySelectorAll('[data-ring]').forEach(fillRing);
  document.querySelectorAll('progress[data-bar]').forEach(fillBar);
  document.querySelectorAll('form[data-transfer]').forEach(wireTransfer);

  // Le message de confirmation s'efface tout seul.
  document.querySelectorAll('.flash').forEach(function (f) {
    setTimeout(function () {
      f.classList.add('leaving');
      setTimeout(function () { f.remove(); }, reduce ? 0 : 600);
    }, 4500);
  });

  // Le menu « Plus » se referme quand on touche ailleurs.
  var more = document.querySelector('details.more');
  if (more) document.addEventListener('click', function (ev) { if (more.open && !more.contains(ev.target)) more.open = false; });
})();
