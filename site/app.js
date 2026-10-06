/* Mobile textbook reader.
 * Plain JavaScript, no build step, no external libraries, so it runs on cheap Android phones
 * and keeps working offline. Books live in books/<id>/book.json (see tools/convert.py).
 * The same file also runs inside a standalone single-file book (window.EMBEDDED_BOOK). */
(function () {
  'use strict';

  var EMB = window.EMBEDDED_BOOK || null;
  // Address of the small server that receives error reports and uploaded books (backend/ in the repo).
  // It runs on the same Cloudflare site as the app, so it exists only there; elsewhere (the old GitHub Pages
  // address, a local copy) API is empty and the "report an error" button and the upload form stay hidden.
  var API = /(^|\.)elkitep\.com$|\.workers\.dev$|^localhost:8787$/.test(location.host) ? '/api' : '';
  // On elkitep.com book pictures come straight from the R2 bucket's own address (its CORS policy lets the app save
  // them for offline reading),
  // so they don't count against the Worker's daily request limit. Elsewhere they sit next to book.json.
  var IMG = /(^|\.)elkitep\.com$/.test(location.host) ? 'https://img.elkitep.com/' : '';
  function picBase(id) { return IMG ? IMG + id + '/' : 'books/' + id + '/'; }

  // ---------------------------------------------------------------- strings
  var I18N = {
    ru: {
      appTitle: 'Школьные учебники', appSub: 'Учебники Кыргызстана, удобные для телефона. Работают без интернета после скачивания.',
      read: 'Читать', cont: 'Продолжить', download: 'Скачать для чтения без интернета', downloading: 'Скачиваю…',
      downloaded: 'Скачано, можно читать без интернета', remove: 'Удалить с телефона',
      grade: 'класс', mb: 'МБ', contents: 'Содержание', settings: 'Настройки', fontSize: 'Размер текста',
      spacing: 'Межстрочный интервал', theme: 'Фон', font: 'Шрифт', serif: 'С засечками', sans: 'Без засечек',
      light: 'Светлый', sepia: 'Сепия', dark: 'Тёмный', contrast: 'Контраст', lang: 'Язык интерфейса',
      page: 'стр.', gotoPage: 'Перейти к странице учебника', go: 'Перейти', back: 'Назад',
      notFound: 'Такой страницы нет', offline: 'Нет интернета. Эта книга ещё не скачана.', err: 'Ошибка загрузки',
      removed: 'Удалено', dlDone: 'Книга скачана', end: 'Конец книги', source: 'Источник', loading: 'Загрузка…',
      noStorage: 'Этот браузер не поддерживает скачивание. Используйте «Сохранить одним файлом».',
      close: 'Закрыть',
      noBooks: 'Таких книг пока нет.',
      my: 'Мои книги', allBooks: 'Все книги', myAdded: 'Добавлено в «Мои книги»',
      myRemoved: 'Убрано из «Моих книг»', myEmpty: 'Здесь будут книги, которые вы открыли или добавили.',
      removeAsk: 'Удалить скачанную книгу с телефона?',
      share: 'Поделиться', shareLink: 'Отправить ссылку', shareFile: 'Отправить файлом',
      shareFileNote: 'Один HTML-файл: откроется в браузере без интернета. На iPhone не открывается.',
      linkCopied: 'Ссылка скопирована', fileSaved: 'Файл сохранён', fileReady: 'Файл готов, отправить', preparing: 'Готовлю файл…',
      quality: 'Качество текста', qExact: 'Точный текст', qProofread: 'Скан, вычитан ИИ', qOcr: 'Скан, без вычитки',
      qExactInfo: 'Текст взят из цифровой версии учебника (PDF) как есть. Ошибок распознавания в нём нет.',
      qProofreadInfo: 'Страницы учебника отсканированы, текст распознан программой (OCR) и исправлен автоматически. Затем искусственный интеллект прочитал всю книгу и исправил ошибки, а в трудных местах сверил текст со сканом. Человек книгу не вычитывал, поэтому отдельные ошибки возможны.',
      qOcrInfo: 'Страницы учебника отсканированы, текст распознан программой (OCR), ошибки исправлены только автоматически. Книгу никто не вычитывал, поэтому в словах встречаются ошибки.',
      qGaps: 'Часть текста не удалось восстановить из скана на страницах: ',
      menu: 'Меню', news: 'Что нового', missing: 'Недостающие учебники',
      newsSub: 'Новые книги и изменения на сайте.', booksInEntry: 'Книги', open: 'Открыть',
      missingSub: 'Эти учебники для 7–11 классов есть в списке Министерства образования на 2026–2027 учебный год, но целиком в интернете мы их не нашли.',
      mNotfound: 'Не найден в интернете', mSample: 'Есть только отрывок', mClosed: 'Нет в открытом доступе',
      mKyonly: 'Есть только на кыргызском', mEdition: 'Есть только другое издание', mKyLink: 'Кыргызская версия',
      haveIt: 'У вас есть один из этих учебников?', haveItJump: 'Есть один из них? Пришлите нам',
      haveItText: 'Пришлите PDF-файл или фотографии страниц, и мы добавим учебник на сайт, чтобы его могли читать все школьники.',
      uploadSoon: 'Отправить файл прямо отсюда можно будет совсем скоро.',
      upBook: 'Какой учебник', upOther: 'Другой учебник', upFiles: 'Файлы (PDF или фото страниц)', upContact: 'Как с вами связаться (необязательно)',
      upComment: 'Комментарий (необязательно)', upSend: 'Отправить', upSending: 'Отправляю…', upDone: 'Спасибо! Файлы получены, мы их посмотрим.',
      upNoFiles: 'Выберите файлы', upTooBig: 'Файл слишком большой (больше 500 МБ): ',
      upFull: 'Сейчас мы не можем принять новые файлы: место для присланных учебников закончилось. Пожалуйста, попробуйте позже.',
      report: 'Сообщить об ошибке', reportTitle: 'Ошибка в тексте', reportFix: 'Как правильно (если знаете)',
      reportSend: 'Отправить', reportThanks: 'Спасибо! Мы проверим и исправим.',
      reportQueued: 'Нет интернета. Отправим, когда появится связь.', reportHint: 'Выделите слово или фразу в книге, чтобы сообщить об ошибке.'
    },
    ky: {
      appTitle: 'Мектеп китептери', appSub: 'Кыргызстандын окуу китептери телефондо окууга ыңгайлуу. Жүктөп алгандан кийин интернетсиз иштейт.',
      read: 'Окуу', cont: 'Улантуу', download: 'Интернетсиз окуу үчүн жүктөп алуу', downloading: 'Жүктөлүүдө…',
      downloaded: 'Жүктөлдү, интернетсиз окууга болот', remove: 'Телефондон өчүрүү',
      grade: 'класс', mb: 'МБ', contents: 'Мазмуну', settings: 'Жөндөөлөр', fontSize: 'Тамганын өлчөмү',
      spacing: 'Саптардын аралыгы', theme: 'Фон', font: 'Арип', serif: 'Засечкалуу', sans: 'Засечкасыз',
      light: 'Ак', sepia: 'Сепия', dark: 'Караңгы', contrast: 'Контраст', lang: 'Интерфейстин тили',
      page: 'бет', gotoPage: 'Китептин бетине өтүү', go: 'Өтүү', back: 'Артка',
      notFound: 'Мындай бет жок', offline: 'Интернет жок. Бул китеп али жүктөлө элек.', err: 'Жүктөөдө ката кетти',
      removed: 'Өчүрүлдү', dlDone: 'Китеп жүктөлдү', end: 'Китептин аягы', source: 'Булак', loading: 'Жүктөлүүдө…',
      noStorage: 'Бул браузер жүктөөнү колдобойт. «Бир файл катары сактоо» баскычын колдонуңуз.',
      close: 'Жабуу',
      noBooks: 'Азырынча мындай китеп жок.',
      my: 'Менин китептерим', allBooks: 'Бардык китептер', myAdded: '«Менин китептерим» тизмесине кошулду',
      myRemoved: '«Менин китептерим» тизмесинен алынды', myEmpty: 'Бул жерде сиз ачкан же кошкон китептер болот.',
      removeAsk: 'Жүктөлгөн китепти телефондон өчүрөсүзбү?',
      share: 'Бөлүшүү', shareLink: 'Шилтеме жөнөтүү', shareFile: 'Файл катары жөнөтүү',
      shareFileNote: 'Бир HTML-файл: браузерде интернетсиз ачылат. iPhone\'до ачылбайт.',
      linkCopied: 'Шилтеме көчүрүлдү', fileSaved: 'Файл сакталды', fileReady: 'Файл даяр, жөнөтүү', preparing: 'Файл даярдалууда…',
      quality: 'Тексттин сапаты', qExact: 'Так текст', qProofread: 'Скан, ЖИ текшерген', qOcr: 'Скан, текшерилген эмес',
      qExactInfo: 'Текст окуу китебинин санариптик нускасынан (PDF) өзгөртүүсүз алынды. Анда таануу каталары жок.',
      qProofreadInfo: 'Китептин беттери сканерленип, текст программа менен таанылды (OCR) жана автоматтык түрдө оңдолду. Андан кийин жасалма интеллект китепти толугу менен окуп, каталарды оңдоду, татаал жерлерин скан менен салыштырды. Китепти адам текшерген эмес, ошондуктан айрым каталар калышы мүмкүн.',
      qOcrInfo: 'Китептин беттери сканерленип, текст программа менен таанылды (OCR), каталар автоматтык түрдө гана оңдолду. Китепти эч ким окуп текшерген эмес, ошондуктан сөздөрдө каталар кездешет.',
      qGaps: 'Бул беттерде тексттин бир бөлүгүн скандан калыбына келтирүү мүмкүн болгон жок: ',
      menu: 'Меню', news: 'Эмне жаңы', missing: 'Жетишпеген китептер',
      newsSub: 'Жаңы китептер жана сайттагы өзгөрүүлөр.', booksInEntry: 'Китептер', open: 'Ачуу',
      missingSub: '7–11-класстар үчүн бул окуу китептери Билим берүү министрлигинин 2026–2027-окуу жылына тизмесинде бар, бирок биз аларды интернеттен толугу менен таба алган жокпуз.',
      mNotfound: 'Интернеттен табылган жок', mSample: 'Үзүндүсү гана бар', mClosed: 'Ачык жеткиликтүү эмес',
      mKyonly: 'Кыргызча гана бар', mEdition: 'Башка басылышы гана бар', mKyLink: 'Кыргызча нускасы',
      haveIt: 'Сизде ушул китептердин бири барбы?', haveItJump: 'Алардын бири барбы? Бизге жөнөтүңүз',
      haveItText: 'PDF-файлын же беттеринин сүрөттөрүн жөнөтүңүз, биз китепти сайтка кошобуз, бардык окуучулар окуй алышы үчүн.',
      uploadSoon: 'Файлды ушул жерден жөнөтүү мүмкүнчүлүгү жакында пайда болот.',
      upBook: 'Кайсы китеп', upOther: 'Башка китеп', upFiles: 'Файлдар (PDF же беттердин сүрөттөрү)', upContact: 'Сиз менен кантип байланышабыз (милдеттүү эмес)',
      upComment: 'Комментарий (милдеттүү эмес)', upSend: 'Жөнөтүү', upSending: 'Жөнөтүлүүдө…', upDone: 'Рахмат! Файлдар алынды, биз аларды карап чыгабыз.',
      upNoFiles: 'Файлдарды тандаңыз', upTooBig: 'Файл өтө чоң (500 МБдан ашык): ',
      upFull: 'Азыр жаңы файлдарды кабыл ала албайбыз: жөнөтүлгөн китептер үчүн орун толуп калды. Кийинчерээк кайра аракет кылыңыз.',
      report: 'Ката жөнүндө билдирүү', reportTitle: 'Тексттеги ката', reportFix: 'Туурасы кандай (билсеңиз)',
      reportSend: 'Жөнөтүү', reportThanks: 'Рахмат! Биз текшерип, оңдойбуз.',
      reportQueued: 'Интернет жок. Байланыш пайда болгондо жөнөтөбүз.', reportHint: 'Ката жөнүндө билдирүү үчүн китептеги сөздү же сүйлөмдү белгилеңиз.'
    }
  };

  // ---------------------------------------------------------------- storage helpers
  function lsGet(k, def) { try { var v = localStorage.getItem(k); return v == null ? def : JSON.parse(v); } catch (e) { return def; } }
  function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode: ignore */ } }
  function lsDel(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } }

  var defLang = (navigator.language || '').toLowerCase().indexOf('ky') === 0 ? 'ky' : 'ru';
  var S = lsGet('settings', null) || {};
  S.fs = S.fs || 19; S.lh = S.lh || 1.55; S.theme = S.theme || 'light'; S.font = S.font || 'serif'; S.ui = S.ui || defLang;

  function t(k) { return (I18N[S.ui] || I18N.ru)[k] || I18N.ru[k] || k; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function $(sel, root) { return (root || document).querySelector(sel); }

  var THEME_BG = { light: '#ffffff', sepia: '#f5ecd9', dark: '#111315', contrast: '#000000' };
  function applySettings() {
    var r = document.documentElement;
    r.setAttribute('data-theme', S.theme);
    r.setAttribute('data-font', S.font);
    r.style.setProperty('--fs', S.fs + 'px');
    r.style.setProperty('--lh', String(S.lh));
    r.lang = S.ui;
    var m = $('meta[name=theme-color]'); if (m) m.setAttribute('content', THEME_BG[S.theme]);
    lsSet('settings', S);
  }

  var toastTimer;
  function toast(msg) {
    var el = $('.toast');
    if (!el) { el = document.createElement('div'); el.className = 'toast'; document.body.appendChild(el); }
    el.textContent = msg; el.style.display = 'block';
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { el.style.display = 'none'; }, 2600);
  }

  function fetchJSON(url) {
    // revalidate with the server, so a corrected book or a new book list shows up on the next visit
    return fetch(url, { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  var app = document.getElementById('app');
  var cleanup = null; // reader teardown

  function route() {
    if (cleanup) { cleanup(); cleanup = null; }
    if (EMB) return openReader(EMB.id);
    var m = location.hash.match(/^#\/read\/([\w.-]+)/);
    if (m) openReader(m[1]);
    else if (location.hash === '#/my') showMyBooks();
    else if (location.hash === '#/news') showNews();
    else if (location.hash === '#/missing') showMissing();
    else showLibrary();
  }

  // ================================================================ LIBRARY
  function cacheName(b) { return 'book-' + b.id + '-' + b.v; }

  // The library is organised by school (language of instruction), then grade, then subject.
  // Choosing the school also sets the interface language.
  var SCHOOLS = [['ky', 'Кыргыз мектеби'], ['ru', 'Русская школа']];

  // Subjects in the order the ministry lists them. A book's subject comes from its "subject"
  // field when index.json has one, otherwise from its title; a title that matches nothing
  // becomes its own subject, so new books always show up.
  var SUBJECTS = [
    ['kyrgyz-tili', /кыргыз тили|кыргызский язык/, 'Кыргыз тили', 'Кыргызский язык'],
    ['kyrgyz-adabiyat', /кыргыз адабият|кыргызская литература/, 'Кыргыз адабияты', 'Кыргызская литература'],
    ['russkiy-yazyk', /русский язык|орус тили/, 'Орус тили', 'Русский язык'],
    ['russkaya-literatura', /русская литература|литературное чтение|орус адабият/, 'Орус адабияты', 'Русская литература'],
    ['adabiyat', /адабият|литератур/, 'Адабият', 'Литература'],
    ['matematika', /математик|алгебр|геометр/, 'Математика', 'Математика'],
    ['fizika', /физик/, 'Физика', 'Физика'],
    ['himiya', /хими/, 'Химия', 'Химия'],
    ['biologiya', /биолог/, 'Биология', 'Биология'],
    ['geografiya', /географ/, 'География', 'География'],
    ['istoriya-kg', /кыргызстан\S* тарых|история кыргызстана/, 'Кыргызстандын тарыхы', 'История Кыргызстана'],
    ['istoriya-mir', /дүйнө тарых|орто кылым|жаңы тарых|соңку тарых|байыркы|всемирная история|средних век|новая история|новейшая история|древн/, 'Дүйнө тарыхы', 'Всемирная история'],
    ['religii', /диндер|религи/, 'Диндердин тарыхы', 'История религий'],
    ['obshchestvo', /адам жана коом|человек и общество/, 'Адам жана коом', 'Человек и общество'],
    ['grazhdanstvennost', /гражданствен|жарандык/, 'Жарандык', 'Гражданственность'],
    ['english', /англ|english/, 'Англис тили', 'Английский язык']
  ];
  function subjectOf(b) {
    var s = String(b.subject || b.title || '').toLowerCase();
    for (var i = 0; i < SUBJECTS.length; i++) {
      if (b.subject === SUBJECTS[i][0] || SUBJECTS[i][1].test(s)) return { key: SUBJECTS[i][0], order: i, name: SUBJECTS[i][S.ui === 'ky' ? 2 : 3] };
    }
    return { key: 'x:' + s, order: SUBJECTS.length, name: b.subject || b.title };
  }

  // "My books": books the reader opened or added, stored on the phone. 1 = in the list,
  // 0 = removed by the reader. Books opened before this list existed count as added.
  function myState() { return lsGet('mybooks', null) || {}; }
  function inMy(id) { var s = myState()[id]; return s === 1 || (s !== 0 && !!lsGet('pos:' + id, null)); }
  function setMy(id, on) { var s = myState(); s[id] = on ? 1 : 0; lsSet('mybooks', s); }

  var libHash = '#/'; // where the reader's back button returns to

  function libShell(title, link, main) { // main: the library page (intro text and school switch)
    document.title = title;
    var school = S.school || (S.ui === 'ky' ? 'ky' : 'ru');
    app.innerHTML = '<div class="lib"><div class="lib-head"><button class="icon burger" aria-label="' + esc(t('menu')) + '">' + ICONS.menu + '</button><h1>' + esc(title) + '</h1>' + link + '</div>' +
      (main ? '<p class="sub">' + esc(t('appSub')) + '</p><div class="school">' + SCHOOLS.map(function (o) {
        return '<button data-s="' + o[0] + '"' + (o[0] === school ? ' class="on"' : '') + '>' + esc(o[1]) + '</button>';
      }).join('') + '</div>' : '') +
      '<div id="books"><div class="loading">' + esc(t('loading')) + '</div></div></div>';
    $('.burger', app).onclick = openMenu;
    Array.prototype.forEach.call(app.querySelectorAll('.school button'), function (btn) {
      btn.onclick = function () {
        S.school = S.ui = btn.getAttribute('data-s'); applySettings();
        route(); // redraw the page we are on (setting the same hash would not fire hashchange)
      };
    });
    return school;
  }

  var LIST = null; // the last book list loaded, for the reader's quality badge
  function loadList() {
    return fetchJSON('books/index.json').then(function (list) { LIST = list; return list; }).catch(function (e) {
      $('#books').innerHTML = '<div class="loading">' + esc(t('err')) + '</div>'; throw e;
    });
  }

  function showLibrary() {
    libHash = '#/';
    var school = libShell(t('appTitle'), '<a class="btn my-link" href="#/my">' + esc('★ ' + t('my')) + '</a>', true);
    loadList().then(function (list) {
      list = list.filter(function (b) { return !b.school || b.school === school; });
      var grades = [];
      list.forEach(function (b) { gradesOf(b).forEach(function (g) { if (grades.indexOf(g) < 0) grades.push(g); }); });
      grades.sort(function (a, b) { return a - b; });
      var open = lsGet('libOpen', {});
      var box = $('#books');
      box.innerHTML = grades.length ? '' : '<div class="loading">' + esc(t('noBooks')) + '</div>';
      grades.forEach(function (g) {
        var books = list.filter(function (b) { return gradesOf(b).indexOf(g) >= 0; });
        var sec = document.createElement('section'); sec.className = 'grade';
        sec.innerHTML = '<button class="grade-h"><span>' + esc(g + ' ' + t('grade')) + '</span><span class="n">' + books.length + '</span></button><div class="grade-b"></div>';
        var head = $('.grade-h', sec), body = $('.grade-b', sec);
        function setOpen(on) {
          sec.classList.toggle('open', on);
          body.innerHTML = '';
          if (on) bySubject(books, body, false);
        }
        head.onclick = function () {
          var on = !sec.classList.contains('open');
          Array.prototype.forEach.call(box.querySelectorAll('.grade.open'), function (s) { if (s !== sec) { s.classList.remove('open'); $('.grade-b', s).innerHTML = ''; } });
          setOpen(on);
          open[school] = on ? g : null; lsSet('libOpen', open);
          if (on && sec.scrollIntoView) sec.scrollIntoView({ block: 'start' });
        };
        box.appendChild(sec);
        if (open[school] === g) setOpen(true);
      });
    });
  }

  function showMyBooks() {
    libHash = '#/my';
    libShell(t('my'), '<a class="btn my-link" href="#/">' + esc('‹ ' + t('allBooks')) + '</a>', false);
    loadList().then(function (list) {
      var box = $('#books');
      var mine = list.filter(function (b) { return inMy(b.id); });
      box.innerHTML = '';
      if (!mine.length) { box.innerHTML = '<div class="loading">' + esc(t('myEmpty')) + '</div>'; return; }
      var grades = [];
      mine.forEach(function (b) { var g = gradesOf(b)[0]; if (grades.indexOf(g) < 0) grades.push(g); });
      grades.sort(function (a, b) { return (a == null ? 99 : a) - (b == null ? 99 : b); });
      grades.forEach(function (g) {
        var sec = document.createElement('section'); sec.className = 'grade open';
        sec.innerHTML = '<h2 class="grade-t">' + esc(g == null ? '' : g + ' ' + t('grade')) + '</h2><div class="grade-b"></div>';
        bySubject(mine.filter(function (b) { return gradesOf(b)[0] === g; }), $('.grade-b', sec), true);
        box.appendChild(sec);
      });
    });
  }

  // The menu (☰ in the library header): the site's pages, as a panel sliding in from the left.
  function openMenu() {
    var bg = document.createElement('div'); bg.className = 'sheet-bg';
    var nav = document.createElement('nav'); nav.className = 'drawer';
    var cur = location.hash || '#/';
    var items = [['#/', t('allBooks')], ['#/my', '★ ' + t('my')], ['#/missing', t('missing')], ['#/news', t('news')]];
    nav.innerHTML = '<div class="drawer-h"><span>' + esc(t('appTitle')) + '</span><button class="icon x" aria-label="' + esc(t('close')) + '">' + ICONS.close + '</button></div>' +
      items.map(function (it) { return '<a href="' + it[0] + '"' + (it[0] === cur ? ' class="cur"' : '') + '>' + esc(it[1]) + '</a>'; }).join('') +
      (API ? '<p class="note">' + esc(t('reportHint')) + '</p>' : '');
    document.body.appendChild(bg); document.body.appendChild(nav);
    function close() { bg.remove(); nav.remove(); }
    bg.onclick = close; $('.x', nav).onclick = close;
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) close(); });
  }

  var MONTHS = {
    ru: ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'],
    ky: ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
  };
  function fmtDate(d) { // "2026-09-29" -> "29 сентября 2026" / "29-сентябрь, 2026"
    var m = String(d).match(/^(\d{4})-(\d\d)-(\d\d)/); if (!m) return d;
    return S.ui === 'ky' ? +m[3] + '-' + MONTHS.ky[+m[2] - 1] + ', ' + m[1] : +m[3] + ' ' + MONTHS.ru[+m[2] - 1] + ' ' + m[1];
  }
  function bookLink(b) {
    return '<a href="#/read/' + esc(b.id) + '">' + esc(b.title + (b.grade ? ', ' + b.grade + ' ' + t('grade') : '')) + '</a>';
  }

  // "What's new": site/changelog.json, newest first. Each entry: {"date": "YYYY-MM-DD", "ru": "...", "ky": "...",
  // "books": [book ids, optional]}. Book-publishing threads add an entry at the top with every publish.
  function showNews() {
    libHash = '#/news';
    libShell(t('news'), '', false);
    Promise.all([fetchJSON('changelog.json'), LIST ? LIST : loadList().catch(function () { return []; })]).then(function (r) {
      var byId = {}; r[1].forEach(function (b) { byId[b.id] = b; });
      var log = r[0].slice().sort(function (a, b) { return a.date < b.date ? 1 : a.date > b.date ? -1 : 0; });
      var html = '<p class="sub">' + esc(t('newsSub')) + '</p>', last = null;
      log.forEach(function (e) {
        if (e.date !== last) { html += '<h2 class="news-d">' + esc(fmtDate(e.date)) + '</h2>'; last = e.date; }
        var books = (e.books || []).map(function (id) { return byId[id]; }).filter(Boolean);
        html += '<div class="news"><p>' + esc(e[S.ui] || e.ru) + '</p>' + (books.length ?
          (books.length > 4 ? '<details><summary>' + esc(t('booksInEntry') + ' (' + books.length + ')') + '</summary>' : '<div>') +
          '<ul class="news-b">' + books.map(function (b) { return '<li>' + bookLink(b) + '</li>'; }).join('') + '</ul>' +
          (books.length > 4 ? '</details>' : '</div>') : '') + '</div>';
      });
      $('#books').innerHTML = html;
    }).catch(function () { $('#books').innerHTML = '<div class="loading">' + esc(navigator.onLine === false ? t('offline') : t('err')) + '</div>'; });
  }

  // Approved textbooks we could not find online: site/missing.json. Each entry: {"school": "ru"|"ky", "grade", "title",
  // "authors", "status": notfound|sample|closed|kyonly|edition, "note_ru", "note_ky", "live": id of a version in the library}.
  // A book that goes live is removed from that file.
  var MSTATUS = { notfound: 'mNotfound', sample: 'mSample', closed: 'mClosed', kyonly: 'mKyonly', edition: 'mEdition' };
  function showMissing() {
    libHash = '#/missing';
    libShell(t('missing'), '', false);
    Promise.all([fetchJSON('missing.json'), LIST ? LIST : loadList().catch(function () { return []; })]).then(function (r) {
      var byId = {}; r[1].forEach(function (b) { byId[b.id] = b; });
      var list = r[0], school = S.school || (S.ui === 'ky' ? 'ky' : 'ru');
      var html = '<p class="sub">' + esc(t('missingSub')) + '</p><p><button class="btn jump">' + esc(t('haveItJump') + ' ↓') + '</button></p>';
      SCHOOLS.filter(function (sc) { return sc[0] === school; }).concat(SCHOOLS.filter(function (sc) { return sc[0] !== school; })).forEach(function (sc) {
        var rows = list.filter(function (m) { return m.school === sc[0]; });
        if (!rows.length) return;
        html += '<h2 class="grade-t">' + esc(sc[1]) + '</h2>';
        var lastG = null;
        rows.forEach(function (m) {
          if (m.grade !== lastG) { html += '<h3 class="subj">' + esc(m.grade + ' ' + t('grade')) + '</h3>'; lastG = m.grade; }
          var live = m.live && byId[m.live];
          html += '<div class="bk miss"><div class="bk-t">' + esc(m.title) + '</div><div class="bk-m">' + esc(m.authors || '') + '</div>' +
            '<div><span class="ms ms-' + esc(m.status) + '">' + esc(t(MSTATUS[m.status] || 'mNotfound')) + '</span></div>' +
            ((m['note_' + S.ui] || m.note_ru) ? '<div class="note">' + esc(m['note_' + S.ui] || m.note_ru) + '</div>' : '') +
            (live ? '<div class="note">' + esc(t('mKyLink')) + ': ' + bookLink(live) + '</div>' : '') + '</div>';
        });
      });
      html += '<div class="offer" id="offer"><h2>' + esc(t('haveIt')) + '</h2><p>' + esc(t('haveItText')) + '</p>' +
        (API ? '' : '<p class="note">' + esc(t('uploadSoon')) + '</p>') + '</div>';
      $('#books').innerHTML = html;
      $('.jump', app).onclick = function () { $('#offer').scrollIntoView({ block: 'start', behavior: 'smooth' }); };
      if (API) uploadForm($('#offer'), list);
    }).catch(function () { $('#books').innerHTML = '<div class="loading">' + esc(navigator.onLine === false ? t('offline') : t('err')) + '</div>'; });
  }

  // ---- sending to the server (API): error reports and uploaded books
  function api(path, opts) {
    return fetch(API + path, opts).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function postJSON(path, data) {
    // text/plain keeps this a "simple" request (no CORS preflight), which is faster on slow phones
    return api(path, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=UTF-8' }, body: JSON.stringify(data) });
  }
  // Reports made offline wait on the phone and go out with the next one, or when the app opens online.
  function sendReports() {
    var q = lsGet('reports', []);
    if (!API || !q.length || navigator.onLine === false) return Promise.resolve(false);
    var r = q[0];
    return postJSON('/reports', r).then(function () {
      lsSet('reports', lsGet('reports', []).filter(function (x) { return x.at !== r.at; }));
      return sendReports().then(function () { return true; });
    }, function () { return false; });
  }
  function report(r) {
    r.at = Date.now();
    lsSet('reports', lsGet('reports', []).concat([r]));
    return sendReports();
  }

  var CHUNK = 8 * 1048576, MAX_FILE = 500 * 1048576;
  function uploadForm(box, list) {
    var f = document.createElement('form'); f.className = 'up';
    f.innerHTML = '<label>' + esc(t('upBook')) + '</label><select name="book">' + list.map(function (m, i) {
      return '<option value="' + i + '">' + esc(m.title + ', ' + m.grade + ' ' + t('grade') + ' (' + m.authors + ')') + '</option>';
    }).join('') + '<option value="-1">' + esc(t('upOther')) + '</option></select>' +
      '<label>' + esc(t('upFiles')) + '</label><input type="file" name="files" multiple accept="application/pdf,image/*">' +
      '<label>' + esc(t('upContact')) + '</label><input type="text" name="contact" maxlength="200" autocomplete="off">' +
      '<label>' + esc(t('upComment')) + '</label><textarea name="comment" rows="2" maxlength="2000"></textarea>' +
      '<button class="btn primary" type="submit">' + esc(t('upSend')) + '</button><div class="progress" hidden><i></i></div>';
    box.appendChild(f);
    var btn = $('button', f), prog = $('.progress', f), bar = $('.progress i', f);
    f.onsubmit = function (e) {
      e.preventDefault();
      var files = Array.prototype.slice.call(f.files.files);
      if (!files.length) { toast(t('upNoFiles')); return; }
      for (var i = 0; i < files.length; i++) if (files[i].size > MAX_FILE) { toast(t('upTooBig') + files[i].name); return; }
      var m = list[+f.book.value], total = files.reduce(function (a, x) { return a + x.size; }, 0) || 1, sent = 0;
      btn.disabled = true; btn.textContent = t('upSending'); prog.hidden = false; bar.style.width = '0';
      postJSON('/uploads', { book: m ? m.title + ', ' + m.grade + ' (' + m.school + '): ' + m.authors : 'other', contact: f.contact.value, comment: f.comment.value, lang: S.ui })
        .then(function (up) {
          // each file goes in pieces, so a big scan survives a slow mobile connection
          return files.reduce(function (p, file) {
            return p.then(function () {
              return postJSON('/uploads/' + up.id + '/files', { name: file.name, size: file.size, type: file.type }).then(function (fr) {
                var parts = [], n = 0;
                function next() {
                  var start = n * CHUNK; if (start >= file.size && n > 0) return Promise.resolve();
                  var piece = file.slice(start, start + CHUNK), num = ++n;
                  return api('/uploads/' + up.id + '/files/' + fr.file + '/' + num, { method: 'PUT', body: piece }).then(function (pr) {
                    parts.push({ n: num, etag: pr.etag }); sent += piece.size; bar.style.width = Math.round(sent / total * 100) + '%';
                    return next();
                  });
                }
                return next().then(function () { return postJSON('/uploads/' + up.id + '/files/' + fr.file + '/done', { parts: parts }); });
              });
            });
          }, Promise.resolve());
        })
        .then(function () { f.innerHTML = '<p class="done">' + esc(t('upDone')) + '</p>'; })
        .catch(function (e) {
          if (e && e.message === '507') { f.innerHTML = '<p class="done">' + esc(t('upFull')) + '</p>'; return; } // storage full (MAX_TOTAL in the Worker)
          btn.disabled = false; btn.textContent = t('upSend'); prog.hidden = true; toast(navigator.onLine === false ? t('offline') : t('err')); });
    };
  }

  // Books under subject headings; subjects without books are never shown.
  function bySubject(books, root, myView) {
    var groups = {}, keys = [];
    books.forEach(function (b) {
      var s = subjectOf(b);
      if (!groups[s.key]) { groups[s.key] = { s: s, books: [] }; keys.push(s.key); }
      groups[s.key].books.push(b);
    });
    keys.sort(function (a, b) { var x = groups[a].s, y = groups[b].s; return x.order - y.order || (x.name < y.name ? -1 : x.name > y.name ? 1 : 0); });
    keys.forEach(function (k) {
      var h = document.createElement('h3'); h.className = 'subj'; h.textContent = groups[k].s.name;
      root.appendChild(h);
      groups[k].books.forEach(function (b) { root.appendChild(bookRow(b, myView)); });
    });
  }

  // "7", 7, "7–9" or "10-11" -> [7], [7, 8, 9], [10, 11]
  function gradesOf(b) {
    var m = String(b.grade == null ? '' : b.grade).match(/(\d+)\s*[–-]\s*(\d+)|(\d+)/);
    if (!m) return [];
    if (m[3]) return [+m[3]];
    var out = []; for (var g = +m[1]; g <= +m[2]; g++) out.push(g); return out;
  }

  var IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var LIB_ICONS = {
    star: '<svg viewBox="0 0 24 24"><path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/></svg>',
    dl: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/></svg>',
    done: '<svg viewBox="0 0 24 24"><path d="M5 20h14M7.5 11.5l3 3 6-6.5"/></svg>',
    share: IS_IOS
      ? '<svg viewBox="0 0 24 24"><path d="M12 3v12M8 7l4-4 4 4"/><path d="M8.5 10H6.5a1.5 1.5 0 0 0-1.5 1.5v8A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5v-8a1.5 1.5 0 0 0-1.5-1.5h-2"/></svg>'
      : '<svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.5M8.2 13.2l7.6 4.5"/></svg>'
  };

  function bookRow(b, myView) {
    var el = document.createElement('div'); el.className = 'bk';
    var hasPos = !!lsGet('pos:' + b.id, null);
    var mb = (b.size / 1048576).toFixed(1);
    var meta = [[b.author, b.year].filter(Boolean).join(', ')];
    if (gradesOf(b).length > 1) meta.push(b.grade + ' ' + t('grade'));
    if (myView && b.school) meta.push(b.school === 'ky' ? 'Кыргыз мектеби' : 'Русская школа');
    meta.push(mb + ' ' + t('mb'));
    el.innerHTML = '<div class="bk-h"><div class="bk-t">' + esc(b.title) + '</div>' +
      '<button class="icon star" aria-label="' + esc(t('my')) + '">' + LIB_ICONS.star + '</button></div>' +
      (b.subtitle ? '<div class="bk-s">' + esc(b.subtitle) + '</div>' : '') +
      '<div class="bk-m">' + esc(meta.filter(Boolean).join(' · ')) + '</div>' +
      '<div class="row"><a class="btn primary" href="#/read/' + esc(b.id) + '">' + esc(hasPos ? t('cont') : t('read')) + '</a>' +
      '<button class="icon dl"></button><button class="icon share" aria-label="' + esc(t('share')) + '">' + LIB_ICONS.share + '</button>' + qBadge(b) + '</div>' +
      '<div class="progress" hidden><i></i></div>';
    var btn = $('.dl', el), prog = $('.progress', el), bar = $('.progress i', el), star = $('.star', el);

    function setStar() { star.classList.toggle('on', inMy(b.id)); star.setAttribute('aria-pressed', inMy(b.id) ? 'true' : 'false'); }
    star.onclick = function () {
      var on = !inMy(b.id);
      setMy(b.id, on); toast(on ? t('myAdded') : t('myRemoved'));
      if (!on && myView) {
        var body = el.parentNode, sec = body.parentNode, h = el.previousElementSibling;
        body.removeChild(el);
        // drop a subject heading or grade that is now empty
        if (h && h.className === 'subj' && (!h.nextElementSibling || h.nextElementSibling.className === 'subj')) body.removeChild(h);
        if (!body.children.length) sec.parentNode.removeChild(sec);
        if (!$('.bk', app)) $('#books').innerHTML = '<div class="loading">' + esc(t('myEmpty')) + '</div>';
        return;
      }
      setStar();
    };
    setStar();

    $('.share', el).onclick = function () { shareSheet(b); };
    var qb = $('.q', el); if (qb) qb.onclick = function () { qualitySheet(b); };

    function setState(done) {
      btn.disabled = false;
      btn.innerHTML = done ? LIB_ICONS.done : LIB_ICONS.dl;
      btn.setAttribute('aria-label', done ? t('downloaded') : t('download'));
      btn.classList.toggle('on', done);
      btn.onclick = done ? function () { toast(t('downloaded')); if (window.confirm(t('removeAsk'))) remove(); } : download;
      prog.hidden = true;
    }
    function download(quiet) {
      if (!window.caches) { toast(t('noStorage')); return; }
      btn.disabled = true; prog.hidden = false; bar.style.width = '0'; if (quiet !== true) toast(t('downloading'));
      downloadBook(b, function (f) { bar.style.width = Math.round(f * 100) + '%'; })
        .then(function () { setState(true); if (quiet !== true) toast(t('dlDone')); })
        .catch(function () { setState(false); if (quiet !== true) toast(navigator.onLine === false ? t('offline') : t('err')); });
    }
    function remove() {
      caches.keys().then(function (keys) {
        return Promise.all(keys.filter(function (k) { return k.indexOf('book-' + b.id + '-') === 0; }).map(function (k) { return caches.delete(k); }));
      }).then(function () { lsDel('dl:' + b.id); setState(false); toast(t('removed')); });
    }
    setState(false);
    if (window.caches) {
      caches.has(cacheName(b)).then(function (has) { // caches.open would create an empty cache for every book
        return has && caches.open(cacheName(b)).then(function (c) { return c.match('books/' + b.id + '/book.json'); });
      }).then(function (r) {
        var had = lsGet('dl:' + b.id, null), cur = !!r && had === b.v;
        setState(cur);
        // downloaded before the book was corrected: fetch the new version (only changed files) in the background
        if (!cur && had && navigator.onLine !== false) download(true);
      });
    }
    return el;
  }

  // Share a book: a link (opens the app at the book) or the single-file book, through the
  // phone's own share sheet. Without Web Share the link is copied and the file is saved.
  function shareSheet(b) {
    var name = b.title + (b.grade ? ', ' + b.grade + ' ' + t('grade') : '');
    var url = location.href.split('#')[0] + '#/read/' + b.id;
    var old = $('.sheet'); if (old) old.remove(); old = $('.sheet-bg'); if (old) old.remove();
    var bg = document.createElement('div'); bg.className = 'sheet-bg';
    var sh = document.createElement('div'); sh.className = 'sheet';
    sh.innerHTML = '<h3><span>' + esc(t('share')) + ': ' + esc(name) + '</span><button class="icon x" aria-label="' + esc(t('close')) + '">' + ICONS.close + '</button></h3>' +
      '<div class="share-opts"><button class="btn primary s-link">' + esc(t('shareLink')) + '</button>' +
      (b.standalone ? '<button class="btn s-file">' + esc(t('shareFile')) + '</button><div class="note">' + esc(t('shareFileNote')) + '</div>' : '') + '</div>';
    document.body.appendChild(bg); document.body.appendChild(sh);
    function close() { bg.remove(); sh.remove(); }
    bg.onclick = close; $('.x', sh).onclick = close;

    $('.s-link', sh).onclick = function () {
      if (navigator.share) {
        navigator.share({ title: name, text: name, url: url }).then(close, function () { /* cancelled */ });
      } else if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () { toast(t('linkCopied')); close(); }, function () { window.prompt(t('shareLink'), url); });
      } else {
        window.prompt(t('shareLink'), url);
      }
    };
    var fbtn = $('.s-file', sh);
    if (!fbtn) return;
    var file = null;
    function save() {
      var a = document.createElement('a'); a.href = URL.createObjectURL(file); a.download = file.name;
      document.body.appendChild(a); a.click(); a.remove(); toast(t('fileSaved')); close();
    }
    function send() {
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        navigator.share({ files: [file], title: name }).then(close, function (e) {
          // the tap "expired" while the file was loading: one more tap sends it
          if (e && e.name === 'NotAllowedError') { fbtn.disabled = false; fbtn.textContent = t('fileReady'); fbtn.classList.add('primary'); }
        });
      } else save();
    }
    fbtn.onclick = function () {
      if (file) return send();
      fbtn.disabled = true; fbtn.textContent = t('preparing');
      fetch('books/' + b.id + '/' + b.standalone).then(function (r) { if (!r.ok) throw new Error(r.status); return r.blob(); })
        .then(function (blob) {
          file = new File([blob], b.standalone, { type: 'text/html' });
          fbtn.disabled = false; fbtn.textContent = t('shareFile');
          send();
        })
        .catch(function () { fbtn.disabled = false; fbtn.textContent = t('shareFile'); toast(navigator.onLine === false ? t('offline') : t('err')); });
    };
  }

  // Text quality of a book, from the "quality" field in books/index.json:
  // exact = text of a digital PDF; proofread = OCR of a scan, then read through and corrected by AI;
  // ocr = OCR of a scan with automatic corrections only. "gaps" lists printed pages with text lost in the scan.
  var QUALITY = { exact: 'qExact', proofread: 'qProofread', ocr: 'qOcr' };
  function qBadge(b) {
    var k = b && QUALITY[b.quality];
    return k ? '<button class="q q-' + b.quality + '" aria-label="' + esc(t('quality') + ': ' + t(k)) + '"><i></i>' + esc(t(k)) + '</button>' : '';
  }
  function qualitySheet(b) {
    var k = QUALITY[b.quality]; if (!k) return;
    var old = $('.sheet'); if (old) old.remove(); old = $('.sheet-bg'); if (old) old.remove();
    var bg = document.createElement('div'); bg.className = 'sheet-bg';
    var sh = document.createElement('div'); sh.className = 'sheet qsheet';
    sh.innerHTML = '<h3><span>' + esc(t('quality')) + '</span><button class="icon x" aria-label="' + esc(t('close')) + '">' + ICONS.close + '</button></h3>' +
      '<div class="q q-' + b.quality + '"><i></i>' + esc(t(k)) + '</div>' +
      '<p>' + esc(t(k + 'Info')) + '</p>' +
      (b.quality === 'proofread' && b.gaps ? '<p>' + esc(t('qGaps') + b.gaps + '.') + '</p>' : '');
    document.body.appendChild(bg); document.body.appendChild(sh);
    function close() { bg.remove(); sh.remove(); }
    bg.onclick = close; $('.x', sh).onclick = close;
  }

  function downloadBook(b, onProgress) {
    var base = 'books/' + b.id + '/';
    var cache;
    return caches.open(cacheName(b)).then(function (c) {
      cache = c;
      return fetch(base + 'book.json');
    }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return cache.put(base + 'book.json', r.clone()).then(function () { return r.json(); });
    }).then(function (book) {
      // app files are kept up to date by the service worker (sw.js), not stored with each book
      var urls = book.images.map(function (i) { return picBase(b.id) + i; });
      var done = 0;
      // a few requests in parallel: fast on 3G, gentle on slow phones
      var queue = urls.slice();
      function worker() {
        var u = queue.shift();
        if (!u) return Promise.resolve();
        // a picture already saved with an older version of this book is reused, not downloaded again
        return caches.match(u, { ignoreVary: true }).then(function (hit) {
          if (hit) return cache.put(u, hit);
          return fetch(u, { mode: 'cors' }).then(function (r) { if (!r.ok) throw new Error(u); return cache.put(u, r); });
        }).then(function () { done++; onProgress(done / urls.length); return worker(); });
      }
      if (!urls.length) onProgress(1);
      return Promise.all([worker(), worker(), worker(), worker()]);
    }).then(function () {
      lsSet('dl:' + b.id, b.v);
      if (navigator.storage && navigator.storage.persist) navigator.storage.persist();
      return caches.keys().then(function (keys) { // drop older versions of this book
        return Promise.all(keys.filter(function (k) { return k.indexOf('book-' + b.id + '-') === 0 && k !== cacheName(b); }).map(function (k) { return caches.delete(k); }));
      });
    });
  }

  // ================================================================ READER
  var ICONS = {
    back: '<svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>',
    toc: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10"/></svg>',
    set: '<svg viewBox="0 0 24 24"><path d="M4 20l5-14h2l5 14M6.5 14h7"/><path d="M17 11l2.5-6L22 11M17.8 9h3.4"/></svg>',
    close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    menu: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
    flag: '<svg viewBox="0 0 24 24"><path d="M5 21V4M5 4h11l-2 4 2 4H5"/></svg>'
  };

  function openReader(id) {
    app.innerHTML = '<div class="loading">' + esc(t('loading')) + '</div>';
    if (!EMB) setMy(id, true);
    var p = EMB ? Promise.resolve(EMB) : fetchJSON('books/' + id + '/book.json');
    // the book's entry in the list carries its quality; a book opened from a link loads the list here
    var entry = EMB ? Promise.resolve(EMB) : (LIST ? Promise.resolve(LIST) : loadList().catch(function () { return []; })).then(function (list) {
      return list.filter(function (b) { return b.id === id; })[0] || null;
    });
    Promise.all([p, entry]).then(function (r) { startReader(r[0], EMB ? '' : picBase(id), r[1]); })
      .catch(function () {
        app.innerHTML = '<div class="lib"><p class="loading">' + esc(navigator.onLine === false ? t('offline') : t('err')) +
          '</p><p style="text-align:center"><a class="btn" href="' + libHash + '">' + esc(t('back')) + '</a></p></div>';
      });
  }

  function startReader(book, base, entry) { // base: where the book's pictures are
    document.title = book.title;
    var chapters = book.chapters;
    var posKey = 'pos:' + book.id;

    app.innerHTML =
      '<div class="reader">' +
      '<div class="viewport"><div class="flow" lang="' + esc(book.lang) + '"></div></div>' +
      '<div class="foot"><span class="t"></span><span class="n"></span></div>' +
      '<div class="bar top">' + (EMB ? '' : '<a class="icon" href="' + libHash + '" aria-label="' + esc(t('back')) + '">' + ICONS.back + '</a>') +
      '<div class="title">' + esc(book.title) + '</div>' +
      (qBadge(entry) ? '<button class="icon b-q" aria-label="' + esc(t('quality')) + '"><span class="qdot q-' + entry.quality + '"><i></i></span></button>' : '') +
      '<button class="icon b-toc" aria-label="' + esc(t('contents')) + '">' + ICONS.toc + '</button>' +
      '<button class="icon b-set" aria-label="' + esc(t('settings')) + '">' + ICONS.set + '</button></div>' +
      '<div class="bar bottom"><div class="info"><span class="i1"></span><span class="i2"></span></div>' +
      '<input type="range" class="slider" min="0" max="1" step="1"></div>' +
      '</div>';

    var reader = $('.reader'), vp = $('.viewport'), flow = $('.flow'), footT = $('.foot .t'), footN = $('.foot .n');
    var slider = $('.slider'), i1 = $('.bar .i1'), i2 = $('.bar .i2');

    // original textbook page numbers -> chapter, for "go to page" and the slider
    var pgChapter = {}, pgList = [];
    chapters.forEach(function (c, ci) {
      c.blocks.forEach(function (b) {
        var html = b.h || (b.l ? b.l.join(' ') : '');
        var re = /data-n="(\d+)"/g, m;
        while ((m = re.exec(html))) { var n = +m[1]; if (!(n in pgChapter)) { pgChapter[n] = ci; pgList.push(n); } }
      });
    });
    pgList.sort(function (a, b) { return a - b; });
    if (pgList.length) { slider.min = 0; slider.max = pgList.length - 1; }

    var ch = -1, page = 0, pages = 1, step = 0, colW = 0, H = 0;
    var blockPage = [], pgMarks = []; // [{n, page}]

    function src(s) { return /^data:/.test(s) ? s : base + s; }

    function blockHTML(b, i) {
      var a = ' data-i="' + i + '"';
      switch (b.t) {
        case 'h1': case 'h2': case 'h3': return '<' + b.t + a + '>' + b.h + '</' + b.t + '>';
        case 'p': return '<p' + a + (b.ni ? ' class="ni"' : '') + '>' + b.h + '</p>';
        case 'box': return '<div class="box"' + a + '>' + b.h + '</div>';
        case 'raw': return b.h.replace(/^<(\w+)/, '<$1' + a).replace(/src="img\//g, 'src="' + base + 'img/');
        case 'v': return '<div class="verse"' + a + '>' + b.l.map(function (l) { return l === '' ? '<div class="gap"></div>' : '<div>' + l + '</div>'; }).join('') + '</div>';
        case 'img': return '<figure' + a + '><img data-w="' + b.w + '" data-h="' + b.ht + '"' + (b.dw ? ' style="width:' + b.dw + 'em"' : '') + ' src="' + esc(src(b.src)) + '" alt="' + esc(b.alt || '') + '">' +
          (b.cap ? '<figcaption>' + b.cap + '</figcaption>' : '') + '</figure>';
      }
      return '';
    }

    function renderChapter(ci) {
      ch = ci;
      var c = chapters[ci];
      var html = c.blocks.map(blockHTML).join('');
      if (ci === 0 && qBadge(entry)) html = '<div class="qline">' + qBadge(entry) + '</div>' + html; // on the book's first page
      if (ci === chapters.length - 1) html += '<div class="endnote">— ' + esc(t('end')) + ' —<br>' + esc(t('source')) + ': ' + esc(book.source && book.source.site || '') + '</div>';
      flow.innerHTML = html + '<div class="end"></div>';
      layout();
    }

    function layout() {
      var W = vp.clientWidth; H = vp.clientHeight;
      var pad = Math.max(18, Math.round((W - 680) / 2));
      colW = W - 2 * pad; step = W;
      flow.style.width = colW + 'px';
      flow.style.marginLeft = pad + 'px';
      flow.style.columnWidth = colW + 'px';
      flow.style.columnGap = (2 * pad) + 'px';
      // size images explicitly so pages do not shift when pictures load
      var maxH = H - 32 - 3 * S.fs;
      Array.prototype.forEach.call(flow.querySelectorAll('img[data-w]'), function (img) {
        var w = +img.getAttribute('data-w'), h = +img.getAttribute('data-h');
        var dw = Math.min(colW, maxH * w / h, w * 1.6);
        img.style.width = Math.round(dw) + 'px'; img.style.height = Math.round(dw * h / w) + 'px';
      });
      var fr = flow.getBoundingClientRect();
      var endEl = flow.lastChild;
      pages = Math.max(1, Math.floor((endEl.getBoundingClientRect().left - fr.left + 2) / step) + 1);
      blockPage = [];
      Array.prototype.forEach.call(flow.querySelectorAll('[data-i]'), function (el) {
        blockPage[+el.getAttribute('data-i')] = Math.floor((el.getBoundingClientRect().left - fr.left + 2) / step);
      });
      pgMarks = Array.prototype.map.call(flow.querySelectorAll('.pg'), function (el) {
        return { n: +el.getAttribute('data-n'), page: Math.floor((el.getBoundingClientRect().left - fr.left + 2) / step) };
      });
    }

    function curBlock() {
      var b = 0;
      for (var i = 0; i < blockPage.length; i++) { if (blockPage[i] != null && blockPage[i] <= page) b = i; else if (blockPage[i] > page) break; }
      return b;
    }
    function bookPage() { // textbook page shown at top of this screen
      var n = null;
      for (var i = 0; i < pgMarks.length; i++) { if (pgMarks[i].page <= page) n = pgMarks[i].n; else break; }
      if (n == null) { // before first marker of this chapter: previous chapter's last page
        for (var j = pgList.length - 1; j >= 0; j--) if (pgChapter[pgList[j]] < ch) { n = pgList[j]; break; }
      }
      return n == null ? (pgMarks[0] ? pgMarks[0].n : null) : n;
    }

    function show(p, anim) {
      page = Math.max(0, Math.min(pages - 1, p));
      flow.classList.toggle('anim', !!anim);
      flow.style.transform = 'translate3d(' + (-page * step) + 'px,0,0)';
      var bp = bookPage();
      footT.textContent = chapters[ch].title;
      footN.textContent = (bp != null ? t('page') + ' ' + bp + ' · ' : '') + (page + 1) + '/' + pages;
      i1.textContent = chapters[ch].title;
      i2.textContent = bp != null ? t('page') + ' ' + bp + ' / ' + pgList[pgList.length - 1] : '';
      if (bp != null && document.activeElement !== slider) slider.value = pgList.indexOf(bp);
      lsSet(posKey, { ch: ch, b: curBlock(), at: Date.now() });
    }

    function goBlock(ci, bi) {
      if (ci !== ch) renderChapter(ci);
      show(blockPage[bi] || 0, false);
    }
    function goBookPage(n) {
      if (!(n in pgChapter)) { toast(t('notFound')); return false; }
      if (pgChapter[n] !== ch) renderChapter(pgChapter[n]);
      for (var i = 0; i < pgMarks.length; i++) if (pgMarks[i].n === n) { show(pgMarks[i].page, false); return true; }
      show(0, false); return true;
    }
    function next() {
      if (page < pages - 1) show(page + 1, true);
      else if (ch < chapters.length - 1) { renderChapter(ch + 1); show(0, false); }
      else show(page, true);
    }
    function prev() {
      if (page > 0) show(page - 1, true);
      else if (ch > 0) { renderChapter(ch - 1); show(pages - 1, false); }
      else show(0, true);
    }
    function relayout() { var b = curBlock(); layout(); show(blockPage[b] || 0, false); }

    // ---- touch: swipe to turn pages
    var sx = 0, sy = 0, st = 0, dx = 0, horiz = null, touching = false;
    function selInBook() { var sl = window.getSelection && window.getSelection(); return !!(sl && !sl.isCollapsed && flow.contains(sl.anchorNode)); }
    vp.addEventListener('touchstart', function (e) {
      // two fingers, or moving the handles of selected text: not a page turn
      if (e.touches.length > 1 || selInBook()) { touching = false; return; }
      touching = true; horiz = null; dx = 0;
      sx = e.touches[0].clientX; sy = e.touches[0].clientY; st = Date.now();
      flow.classList.remove('anim');
    }, { passive: true });
    vp.addEventListener('touchmove', function (e) {
      if (!touching) return;
      var x = e.touches[0].clientX, y = e.touches[0].clientY;
      dx = x - sx;
      if (horiz === null && (Math.abs(dx) > 8 || Math.abs(y - sy) > 8)) horiz = Math.abs(dx) > Math.abs(y - sy);
      if (horiz) {
        e.preventDefault();
        var atEdge = (dx > 0 && page === 0 && ch === 0) || (dx < 0 && page === pages - 1 && ch === chapters.length - 1);
        flow.style.transform = 'translate3d(' + (-page * step + dx * (atEdge ? 0.25 : 1)) + 'px,0,0)';
      }
    }, { passive: false });
    vp.addEventListener('touchend', function () {
      if (!touching) return; touching = false;
      if (!horiz) return;
      var v = Math.abs(dx) / Math.max(1, Date.now() - st);
      if (dx < -60 || (dx < -20 && v > 0.3)) next();
      else if (dx > 60 || (dx > 20 && v > 0.3)) prev();
      else show(page, true);
    });

    // ---- taps: left third back, right third forward, middle shows menus
    vp.addEventListener('click', function (e) {
      var sel = window.getSelection && String(window.getSelection());
      if (sel) return;
      if (reader.classList.contains('ui')) { reader.classList.remove('ui'); return; }
      if (e.target.closest && e.target.closest('.q')) { qualitySheet(entry); return; }
      var x = e.clientX / vp.clientWidth;
      if (x < 0.3) prev(); else if (x > 0.7) next();
      else if (e.target.tagName === 'IMG' && e.target.closest('figure')) openZoom(e.target);
      else if (e.target.closest && e.target.closest('figure svg')) {
        var sv = e.target.closest('figure svg'), vb = (sv.getAttribute('viewBox') || '0 0 300 150').split(/\s+/);
        var im = document.createElement('img');
        im.setAttribute('data-w', Math.round(vb[2] * 4)); im.setAttribute('data-h', Math.round(vb[3] * 4));
        var xml = sv.outerHTML.indexOf('xmlns=') < 0 ? sv.outerHTML.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"') : sv.outerHTML;
        im.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml.replace(/style="[^"]*"/, ''));
        openZoom(im);
      }
      else reader.classList.add('ui');
    });
    // ---- picture viewer: tap a picture to see it full screen; tap again to enlarge, scroll to move
    function openZoom(img) {
      var z = document.createElement('div'); z.className = 'zoom';
      var big = false;
      z.innerHTML = '<div class="zoom-in"><img alt=""></div><button class="icon zoom-x" aria-label="' + esc(t('close')) + '">' + ICONS.close + '</button>';
      var zi = $('img', z); zi.src = img.src;
      var fit = function () {
        var W = window.innerWidth, H = window.innerHeight, w = +img.getAttribute('data-w'), h = +img.getAttribute('data-h');
        var s = Math.min(W / w, H / h) * (big ? 2.5 : 1);
        zi.style.width = Math.round(w * s) + 'px'; zi.style.height = 'auto'; zi.style.maxWidth = 'none'; zi.style.maxHeight = 'none';
      };
      zi.onclick = function (e) {
        var inr = $('.zoom-in', z), r = zi.getBoundingClientRect();
        var fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
        big = !big; fit();
        if (big) { inr.scrollLeft = fx * zi.offsetWidth - window.innerWidth / 2; inr.scrollTop = fy * zi.offsetHeight - window.innerHeight / 2; }
      };
      $('.zoom-x', z).onclick = function () { z.remove(); document.removeEventListener('keydown', zkey); };
      var zkey = function (e) { if (e.key === 'Escape') { z.remove(); document.removeEventListener('keydown', zkey); } };
      document.addEventListener('keydown', zkey);
      document.body.appendChild(z); fit();
    }

    function onKey(e) {
      if ($('.zoom')) return;
      if ($('.sheet')) { if (e.key === 'Escape') closeSheet(); return; }
      if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); next(); }
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); prev(); }
    }
    document.addEventListener('keydown', onKey);
    var rt; function onResize() { clearTimeout(rt); rt = setTimeout(relayout, 150); }
    window.addEventListener('resize', onResize);
    // wheel on desktop
    var wheelLock = 0;
    vp.addEventListener('wheel', function (e) {
      var d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (Math.abs(d) < 20 || Date.now() < wheelLock) return;
      wheelLock = Date.now() + 350; if (d > 0) next(); else prev();
    }, { passive: true });

    slider.addEventListener('input', function () { i2.textContent = t('page') + ' ' + pgList[+slider.value] + ' / ' + pgList[pgList.length - 1]; });
    slider.addEventListener('change', function () { goBookPage(pgList[+slider.value]); });

    // ---- sheets
    function closeSheet() { var a = $('.sheet'), b = $('.sheet-bg'); if (a) a.remove(); if (b) b.remove(); }
    function openSheet(html) {
      closeSheet();
      var bg = document.createElement('div'); bg.className = 'sheet-bg'; bg.onclick = closeSheet;
      var sh = document.createElement('div'); sh.className = 'sheet'; sh.innerHTML = html;
      document.body.appendChild(bg); document.body.appendChild(sh);
      return sh;
    }

    $('.b-toc').onclick = function () {
      var html = '<h3>' + esc(t('contents')) + '</h3>' +
        '<div class="goto"><input type="number" inputmode="numeric" placeholder="' + esc(t('gotoPage')) + '"><button class="btn primary">' + esc(t('go')) + '</button></div><div class="toc">';
      var lastSec = null;
      chapters.forEach(function (c, ci) {
        if (c.section && c.section !== lastSec) html += '<div class="sec">' + esc(c.section) + '</div>';
        lastSec = c.section || lastSec;
        html += '<a href="#" data-c="' + ci + '" data-b="0"' + (ci === ch ? ' class="cur"' : '') + '>' + esc(c.title) +
          (c.pages ? '<span class="p">' + c.pages[0] + '</span>' : '') + '</a>';
        if (c.sub) {
          c.sub.forEach(function (s) {
            if (s.b != null) html += '<a href="#" class="sub" data-c="' + ci + '" data-b="' + s.b + '">' + esc(s.title) + '</a>';
          });
        } else {
          c.blocks.forEach(function (b, bi) {
            if (b.t === 'h2' && bi > 0) html += '<a href="#" class="sub" data-c="' + ci + '" data-b="' + bi + '">' + b.h.replace(/<[^>]+>/g, '') + '</a>';
          });
        }
      });
      var sh = openSheet(html + '</div>');
      var cur = $('.cur', sh); if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'center' });
      sh.addEventListener('click', function (e) {
        var a = e.target.closest('a[data-c]'); if (!a) return;
        e.preventDefault(); closeSheet(); reader.classList.remove('ui');
        goBlock(+a.getAttribute('data-c'), +a.getAttribute('data-b'));
      });
      var inp = $('input', sh);
      function go() { if (goBookPage(parseInt(inp.value, 10))) { closeSheet(); reader.classList.remove('ui'); } }
      $('.goto button', sh).onclick = go;
      inp.onkeydown = function (e) { if (e.key === 'Enter') go(); };
    };

    var bq = $('.b-q'); if (bq) bq.onclick = function () { qualitySheet(entry); };

    // ---- report a text error: select a word or phrase, then tap the button that appears at the bottom
    var repBtn = null, lastSel = null, hideT;
    function onSel() {
      var sl = window.getSelection(), txt = sl ? String(sl).replace(/\s+/g, ' ').trim() : '';
      if (txt && selInBook()) {
        clearTimeout(hideT);
        var el = sl.anchorNode.nodeType === 1 ? sl.anchorNode : sl.anchorNode.parentNode, blk = el.closest('[data-i]');
        var full = blk ? blk.textContent.replace(/\s+/g, ' ').trim() : '', at = Math.max(0, full.indexOf(txt.slice(0, 40)));
        lastSel = { ch: ch, b: blk ? +blk.getAttribute('data-i') : null, page: bookPage(), quote: txt.slice(0, 1000),
          context: full.slice(Math.max(0, at - 200), at + txt.length + 200) };
        repBtn.hidden = false;
      } else {
        hideT = setTimeout(function () { repBtn.hidden = true; }, 400); // a tap on the button may clear the selection first
      }
    }
    function reportSheet(e) {
      e.preventDefault(); e.stopPropagation();
      if (!lastSel || $('.sheet')) return;
      var r = lastSel;
      var sh = openSheet('<h3><span>' + esc(t('reportTitle')) + '</span><button class="icon x" aria-label="' + esc(t('close')) + '">' + ICONS.close + '</button></h3>' +
        '<blockquote class="rq">' + esc(r.quote) + '</blockquote>' + (r.page > 0 ? '<div class="note">' + esc(t('page') + ' ' + r.page) + '</div>' : '') +
        '<div class="set"><label>' + esc(t('reportFix')) + '</label><textarea class="rfix" rows="3" maxlength="1000"></textarea></div>' +
        '<button class="btn primary rsend">' + esc(t('reportSend')) + '</button>');
      $('.x', sh).onclick = closeSheet;
      $('.rsend', sh).onclick = function () {
        report({ book: book.id, v: entry && entry.v, ch: r.ch, b: r.b, page: r.page, quote: r.quote, context: r.context,
          fix: $('.rfix', sh).value.trim(), lang: S.ui }).then(function (sent) { toast(sent ? t('reportThanks') : t('reportQueued')); });
        closeSheet(); repBtn.hidden = true; lastSel = null;
        if (window.getSelection) window.getSelection().removeAllRanges();
      };
    }
    if (API && !EMB) {
      repBtn = document.createElement('button'); repBtn.className = 'rep'; repBtn.hidden = true;
      repBtn.innerHTML = ICONS.flag + '<span>' + esc(t('report')) + '</span>';
      reader.appendChild(repBtn);
      document.addEventListener('selectionchange', onSel);
      // react on touch down: on phones a tap elsewhere would clear the selection before "click"
      repBtn.addEventListener('touchstart', reportSheet, { passive: false });
      repBtn.addEventListener('mousedown', reportSheet);
      repBtn.addEventListener('click', function (e) { e.preventDefault(); });
    }

    $('.b-set').onclick = function () {
      function seg(key, opts) {
        return '<div class="seg" data-k="' + key + '">' + opts.map(function (o) {
          return '<button data-v="' + o[0] + '"' + (o[2] ? ' class="' + o[2] + (String(S[key]) === String(o[0]) ? ' on' : '') + '"' : (String(S[key]) === String(o[0]) ? ' class="on"' : '')) + '>' + o[1] + '</button>';
        }).join('') + '</div>';
      }
      var sh = openSheet(
        '<h3>' + esc(t('settings')) + '</h3>' +
        '<div class="set"><label>' + esc(t('fontSize')) + '</label><div class="seg"><button data-fs="-2" style="font-size:14px">A−</button><button class="fsv" disabled>' + S.fs + '</button><button data-fs="2" style="font-size:20px">A+</button></div></div>' +
        '<div class="set"><label>' + esc(t('theme')) + '</label>' + seg('theme', [['light', t('light'), 'swatch'], ['sepia', t('sepia'), 'swatch'], ['dark', t('dark'), 'swatch'], ['contrast', t('contrast'), 'swatch']]) + '</div>' +
        '<div class="set"><label>' + esc(t('font')) + '</label>' + seg('font', [['serif', '<span style="font-family:Georgia,serif">' + esc(t('serif')) + '</span>'], ['sans', '<span style="font-family:Roboto,Arial,sans-serif">' + esc(t('sans')) + '</span>']]) + '</div>' +
        '<div class="set"><label>' + esc(t('spacing')) + '</label>' + seg('lh', [[1.35, '1.35'], [1.55, '1.55'], [1.8, '1.8']]) + '</div>' +
        '<div class="set"><label>' + esc(t('lang')) + '</label>' + seg('ui', [['ru', 'Русский'], ['ky', 'Кыргызча']]) + '</div>');
      sh.addEventListener('click', function (e) {
        var b = e.target.closest('button'); if (!b) return;
        if (b.hasAttribute('data-fs')) {
          S.fs = Math.max(13, Math.min(34, S.fs + +b.getAttribute('data-fs')));
          $('.fsv', sh).textContent = S.fs;
        } else {
          var k = b.parentNode.getAttribute('data-k'); if (!k) return;
          var v = b.getAttribute('data-v'); S[k] = k === 'lh' ? +v : v;
          Array.prototype.forEach.call(b.parentNode.children, function (x) { x.classList.toggle('on', x === b); });
          if (k === 'ui') { applySettings(); closeSheet(); route(); return; }
        }
        applySettings(); relayout();
      });
    };

    cleanup = function () {
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
      document.removeEventListener('selectionchange', onSel);
      closeSheet();
    };

    var pos = lsGet(posKey, null);
    if (pos && chapters[pos.ch]) goBlock(pos.ch, pos.b || 0); else { renderChapter(0); show(0, false); }
    // fonts can change metrics after first paint
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(relayout);
  }

  // ---------------------------------------------------------------- boot
  applySettings();
  window.addEventListener('hashchange', route);
  route();
  if (!EMB) { sendReports(); window.addEventListener('online', sendReports); }
  if (!EMB && 'serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
    navigator.serviceWorker.register('sw.js', { updateViaCache: 'none' }).catch(function () { /* offline support unavailable */ });
  }
})();
