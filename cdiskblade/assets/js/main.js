/* ============================================================
   main.js —— 内容注入 + 多界面路由（一镜到底转场）+ 导航胶囊跟随
   无任何第三方依赖；动效尊重 prefers-reduced-motion
   ============================================================ */
(function () {
  'use strict';

  var S = window.SITE || {};
  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 转场时长：出场 300ms 与入场 640ms 交叠，形成连贯的一镜到底 */
  var OUT = 300, IN = 640;

  /* ---------- 取嵌套字段：get(S,'disk.usedPercent') ---------- */
  function get(obj, path) {
    return path.split('.').reduce(function (o, k) {
      return (o && typeof o === 'object' && o[k] !== undefined) ? o[k] : null;
    }, obj);
  }

  /* ============================================================
     1. 注入全站文本 / 链接 / 元信息
     ============================================================ */
  function bindAll() {
    $$('[data-bind]').forEach(function (el) {
      var p = el.getAttribute('data-bind');
      var token = el.getAttribute('data-token') || p.toUpperCase();
      var v = get(S, p);
      el.textContent = (v === null || v === undefined || v === '') ? '{{' + token + '}}' : v;
    });
    $$('[data-href]').forEach(function (el) {
      var v = get(S, el.getAttribute('data-href'));
      if (v) el.setAttribute('href', v);
    });
    $$('[data-mailto]').forEach(function (el) {
      var v = get(S, el.getAttribute('data-mailto'));
      if (v) el.setAttribute('href', 'mailto:' + v);
    });
    if (S.appName) document.title = S.appName + ' · Windows C 盘清理与缓存迁移工具';
    var md = document.querySelector('meta[name="description"]');
    if (md && S.intro) md.setAttribute('content', S.intro.slice(0, 150));
    var ogt = document.querySelector('meta[property="og:title"]');
    if (ogt && S.appName) ogt.setAttribute('content', S.appName + ' · ' + (S.tagline || ''));
  }

  /* ============================================================
     2. 内联 SVG 图标（不引图标库，零额外请求）
     ============================================================ */
  var ICONS = {
    grid:   '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    broom:  '<path d="M15 4.5 9.5 10"/><path d="M13.5 6.5 17.5 10.5 11 17l-4-4z"/><path d="M11 17 6.5 21.5"/><path d="m5 15.5 3.5 3.5"/>',
    move:   '<path d="M4 8.5h11l-3-3"/><path d="M20 15.5H9l3 3"/><path d="M4 4.5v16"/>',
    reset:  '<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4v4.5h-4.5"/>',
    shield: '<path d="M12 3.5 20 6.5v5.5c0 4.3-3.2 7.3-8 8.5-4.8-1.2-8-4.2-8-8.5V6.5z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    heal:   '<path d="M4 12a8 8 0 0 1 13.7-5.6L20 8.5"/><path d="M20 4v4.5h-4.5"/><path d="M20 12a8 8 0 0 1-13.7 5.6L4 15.5"/><path d="M4 20v-4.5h4.5"/>',
    bolt:   '<path d="M13.5 3 6 13.5h5l-1 8 8-11h-5.5z"/>'
  };
  function svg(inner) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + (inner || '') + '</svg>';
  }

  /* ============================================================
     3. 渲染：开发故事 / 功能卡 / 更新日志 / 系统要求
     ============================================================ */
  function renderStory() {
    var box = $('#storyList'); if (!box) return;
    box.innerHTML = (S.story || []).map(function (it, i) {
      return '<li class="story-item">' +
               '<div class="when">' + (it.when || ('第 ' + (i + 1) + ' 段')) + '</div>' +
               '<h3>' + (it.title || ('{{STORY_' + (i + 1) + '_TITLE}}')) + '</h3>' +
               '<p>' + (it.text || ('{{STORY_' + (i + 1) + '_TEXT}}')) + '</p>' +
             '</li>';
    }).join('');
  }
  function renderFeatures() {
    var box = $('#featureGrid'); if (!box) return;
    box.innerHTML = (S.features || []).map(function (f, i) {
      return '<article class="feature">' +
               '<div class="feature-ico">' + svg(ICONS[f.icon] || ICONS.grid) + '</div>' +
               '<h3>' + (f.title || ('{{FEATURE_' + (i + 1) + '_TITLE}}')) + '</h3>' +
               '<p>' + (f.desc || ('{{FEATURE_' + (i + 1) + '_DESC}}')) + '</p>' +
             '</article>';
    }).join('');
  }
  function renderLogs() {
    var box = $('#logList'); if (!box) return;
    box.innerHTML = (S.logs || []).map(function (l, i) {
      var n = i + 1;
      var items = (l.items || []).map(function (x, j) {
        return '<li>' + (x || ('{{LOG_' + n + '_ITEM_' + (j + 1) + '}}')) + '</li>';
      }).join('');
      return '<li class="log-item">' +
               '<div class="log-head">' +
                 '<span class="log-ver">' + (l.version || ('{{LOG_' + n + '_VERSION}}')) + '</span>' +
                 '<span class="log-date">' + (l.date || ('{{LOG_' + n + '_DATE}}')) + '</span>' +
               '</div>' +
               '<ul class="log-items">' + items + '</ul>' +
             '</li>';
    }).join('');
  }
  function renderReqs() {
    var box = $('#reqBody'); if (!box) return;
    box.innerHTML = (S.requirements || []).map(function (r, i) {
      return '<tr' + (r.warn ? ' class="bad"' : '') + '>' +
               '<th scope="row">' + (r.k || ('{{REQ_' + (i + 1) + '_KEY}}')) + '</th>' +
               '<td>' + (r.v || ('{{REQ_' + (i + 1) + '_VALUE}}')) + '</td>' +
             '</tr>';
    }).join('');
  }

  /* ============================================================
     4. 多界面路由：一个模块 = 一个独立界面，切换走连贯转场
     ============================================================ */
  var VIEWS = [], current = null, hTimer = null, stage;

  function viewOf(id) {
    for (var i = 0; i < VIEWS.length; i++) if (VIEWS[i].id === id) return VIEWS[i];
    return null;
  }

  function initRouter() {
    document.documentElement.classList.add('js');   // 有 JS 才启用「一次只显示一个界面」
    stage = $('#views');
    var btns = $$('.nav-btn[data-view]');
    VIEWS = btns.map(function (b) {
      var id = b.getAttribute('data-view');
      return { id: id, btn: b, name: b.textContent.trim(), el: document.getElementById('view-' + id) };
    }).filter(function (v) { return !!v.el; });
    if (!VIEWS.length) return;

    // 起始界面：优先取地址栏 hash（支持直接分享 / 刷新 / 浏览器前进后退）
    var start = (location.hash || '').replace('#', '');
    if (!viewOf(start)) start = VIEWS[0].id;

    VIEWS.forEach(function (v) {
      v.el.classList.remove('active', 'leaving');
      v.btn.addEventListener('click', function (e) { e.preventDefault(); go(v.id); });
    });

    buildPagers();
    show(start, true);

    window.addEventListener('popstate', function () {
      var id = (location.hash || '').replace('#', '');
      if (viewOf(id)) show(id, false, true);
    });
    window.addEventListener('resize', moveMarker);
    window.addEventListener('load', moveMarker);
  }

  /* 每个界面底部补一组「上一个 / 下一个模块」，首尾循环 → 任何界面都不会成为孤岛 */
  function buildPagers() {
    VIEWS.forEach(function (v, i) {
      var prev = VIEWS[(i - 1 + VIEWS.length) % VIEWS.length];
      var next = VIEWS[(i + 1) % VIEWS.length];
      var nav = document.createElement('nav');
      nav.className = 'pager';
      nav.setAttribute('aria-label', '模块间导航');
      nav.innerHTML =
        '<a class="pager-btn" href="#' + prev.id + '" data-view="' + prev.id + '">' +
          '<span class="p-dir">← 上一个模块</span><span class="p-name">' + prev.name + '</span></a>' +
        '<a class="pager-btn next" href="#' + next.id + '" data-view="' + next.id + '">' +
          '<span class="p-dir">下一个模块 →</span><span class="p-name">' + next.name + '</span></a>';
      nav.addEventListener('click', function (e) {
        var a = e.target.closest ? e.target.closest('[data-view]') : null;
        if (a) { e.preventDefault(); go(a.getAttribute('data-view')); }
      });
      v.el.appendChild(nav);
    });
  }

  function go(id) {
    if (id === current) { toTop(); return; }
    if (window.history && history.pushState) history.pushState(null, '', '#' + id);
    else location.hash = id;
    show(id);
  }

  function show(id, first, fromHistory) {
    var to = viewOf(id); if (!to) return;
    var from = current ? viewOf(current) : null;
    current = id;

    VIEWS.forEach(function (v) {
      var on = v.id === id;
      v.btn.classList.toggle('active', on);
      if (on) v.btn.setAttribute('aria-current', 'page');
      else v.btn.removeAttribute('aria-current');
    });
    moveMarker();

    // 出场：旧界面脱离文档流，原地淡出上移；入场：新界面自下方淡入 —— 两者交叠，全程不闪白
    if (from && from.el !== to.el) {
      from.el.classList.add('leaving');
      setTimeout(function () { from.el.classList.remove('active', 'leaving'); }, OUT);
    }
    to.el.classList.remove('leaving');
    to.el.classList.add('active');

    // 容器高度平滑过渡，切换瞬间页面不塌陷、不跳动
    if (stage) {
      stage.style.minHeight = to.el.offsetHeight + 'px';
      clearTimeout(hTimer);
      hTimer = setTimeout(function () { stage.style.minHeight = ''; }, IN);
    }
    if (first) window.scrollTo(0, 0);
    else if (!fromHistory) toTop();
  }

  function toTop() {
    try { window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' }); }
    catch (e) { window.scrollTo(0, 0); }
  }

  /* 导航胶囊：在导航项之间滑动跟随，视觉上把各个界面串成一条线 */
  function moveMarker() {
    var mk = $('#navMarker'), btn = $('.nav-btn.active');
    if (!mk || !btn) return;
    mk.style.width = btn.offsetWidth + 'px';
    mk.style.height = btn.offsetHeight + 'px';
    mk.style.transform = 'translate(' + btn.offsetLeft + 'px,' + btn.offsetTop + 'px)';
    mk.classList.add('on');
  }

  /* ============================================================
     5. SHA256 一键复制
     ============================================================ */
  function initCopy() {
    $$('[data-copy]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var txt = (get(S, btn.getAttribute('data-copy')) || '').toString();
        var done = function () {
          var old = btn.textContent; btn.textContent = '已复制 ✓';
          setTimeout(function () { btn.textContent = old; }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(txt).then(done, function () { fallback(txt, done); });
        } else fallback(txt, done);
      });
    });
    function fallback(txt, cb) {
      var ta = document.createElement('textarea');
      ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); cb(); } catch (e) { /* 忽略 */ }
      document.body.removeChild(ta);
    }
  }

  /* ============================================================
     启动
     ============================================================ */
  function init() {
    bindAll();
    renderStory(); renderFeatures(); renderLogs(); renderReqs();
    initRouter();
    initCopy();
    setTimeout(moveMarker, 60);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
