/* Photo du ticket : réduite puis lue dans le navigateur, avant d'être envoyée à l'appli.
   La photo n'est transmise à aucun service de lecture. Si la lecture échoue, la photo
   est quand même envoyée et le montant se saisit à la main. */
(function () {
  'use strict';
  var form = document.querySelector('form[data-ticket]');
  if (!form || !window.fetch || !window.FormData) return;
  var input = form.querySelector('input[type=file]');
  var status = form.querySelector('[data-reading]');
  var button = form.querySelector('[data-ticket-hide]');
  var base = form.dataset.ocr;                    // dossier des fichiers de lecture
  var MAX_SIDE = 1600, TIMEOUT = 60000;
  if (button) button.hidden = true;

  function say(text) { if (status) { status.hidden = false; status.textContent = text; } }

  function load(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file), img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('image illisible')); };
      img.src = url;
    });
  }

  // Les photos de téléphone font plusieurs Mo : on les ramène à 1600 px avant l'envoi.
  function shrink(img) {
    var k = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
    var canvas = document.createElement('canvas');
    canvas.width = Math.round(img.naturalWidth * k);
    canvas.height = Math.round(img.naturalHeight * k);
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas;
  }

  function toBlob(canvas) {
    return new Promise(function (resolve) { canvas.toBlob(resolve, 'image/jpeg', 0.85); });
  }

  function read(canvas) {
    if (!window.Tesseract) return Promise.resolve('');
    var worker = null;
    var work = window.Tesseract.createWorker('fra', 1, {
      workerPath: base + 'worker.min.js',
      corePath: base,
      langPath: base,
      gzip: true,
      workerBlobURL: false                         // exigé par la politique de sécurité (pas de blob:)
    }).then(function (w) {
      worker = w;
      return w.setParameters({ tessedit_pageseg_mode: '6' });
    }).then(function () {
      return worker.recognize(canvas);
    }).then(function (res) {
      return res.data.text || '';
    });
    var limit = new Promise(function (resolve) { setTimeout(function () { resolve(''); }, TIMEOUT); });
    return Promise.race([work, limit]).catch(function () { return ''; }).then(function (text) {
      if (worker) worker.terminate();
      return text;
    });
  }

  input.addEventListener('change', function () {
    if (!input.files || !input.files.length) return;
    input.disabled = true;
    say('Préparation de la photo…');
    var canvas, text = '';
    load(input.files[0]).then(function (img) {
      canvas = shrink(img);
      say('Lecture du ticket en cours…');
      return read(canvas);
    }).then(function (t) {
      text = t;
      return toBlob(canvas);
    }).then(function (blob) {
      say('Envoi…');
      var data = new FormData();
      data.append('csrf', form.querySelector('input[name=csrf]').value);
      data.append('photo', blob, 'ticket.jpg');
      data.append('ocr_text', text);
      data.append('ocr_tried', '1');
      return fetch(form.action, { method: 'POST', body: data, credentials: 'same-origin' });
    }).then(function (res) {
      if (!res.ok) throw new Error('refus ' + res.status);
      window.location.assign(res.url);
    }).catch(function () {
      input.disabled = false;
      if (button) button.hidden = false;
      say('La photo n\'a pas pu être traitée. Réessaie, ou saisis le montant à la main ci-dessous.');
    });
  });
})();
