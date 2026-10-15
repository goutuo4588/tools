/* =============================================================
   具坊 · 流动极光背景（Aurora Flow Background）
   -------------------------------------------------------------
   风格参考：QQ 电脑版官网下载页 —— 大面积柔和渐变底 +
             缓慢漂移的光带 + 点击处涟漪 / 粒子扩散。
   实现：WebGL 全屏着色器（光带 + 涟漪） + 2D Canvas（粒子扩散）
   依赖：零。单文件，可直接复制到任意页面使用。
   -------------------------------------------------------------
   ★ 所有可调参数集中在下面的 CFG 里（第 1 处）
   ★ 一键静态：网址加 ?bg=static，或 JuFangBG.setStatic(true)
   ============================================================= */
(function () {
  'use strict';

  /* =========================================================
     【第 1 处】可调参数 —— 改这里就够了
     ========================================================= */
  var CFG = {
    /* --- 颜色（HSL 色相循环，连续变化，不会跳变/闪烁） --- */
    hueSpeed:    0.030,  // 色相循环速度：圈/秒。0.03 ≈ 33 秒转一整圈（推荐 0.01~0.12）
    saturation:  0.62,   // 饱和度 0~1。越大越艳（0.45 淡雅 / 0.8 浓烈）
    lightness:   0.74,   // 亮度 0~1。越大越浅（浅色站点建议 ≥0.68，保证文字可读）
    hueSpread:   0.28,   // 画面内的色相跨度：越大，同一屏里颜色越丰富
    baseHue:     0.58,   // 起始色相 0~1（0 红 .33 绿 .58 蓝 .78 紫）

    /* --- 流动光带 --- */
    flowSpeed:   0.085,  // 光带漂移速度（0.03 极慢 / 0.3 明显流动）
    bandCount:   2.6,    // 光带密度：数值越大，条带越密
    bandStrength:0.55,   // 光带强度 0~1：越大越浓（0.3 若隐若现 / 0.85 浓墨重彩）
    warp:        2.4,    // 扭曲程度：越大越"液体感"
    grain:       0.012,  // 细微颗粒，消除大面积渐变的色带断层（0 关闭）

    /* --- 点击涟漪（着色器里的光环） --- */
    ripple:      true,
    rippleSpeed: 0.55,   // 涟漪扩散速度（屏宽/秒）
    rippleLife:  2.2,    // 涟漪存活秒数
    rippleGlow:  0.22,   // 涟漪亮度 0~0.6
    maxRipples:  8,      // 同时存在的涟漪数（与着色器数组长度一致，别超过 8）

    /* --- 点击粒子扩散（2D 层） --- */
    particles:     true,
    particleCount: 16,   // 每次点击的粒子数
    particleSpeed: 190,  // 粒子初速 px/s
    particleLife:  1.15, // 粒子存活秒数
    particleSize:  2.6,  // 粒子半径 px

    /* --- 性能 --- */
    resolutionScale: 0.6, // 渲染分辨率倍率（0.4 省电 / 1.0 清晰）。光带很模糊，0.6 足够
    maxFps:          60,  // 帧率上限（30 可明显省电）

    /* --- 模式 --- */
    enabled: true,        // 总开关：false = 完全不启动（等同静态背景）
    static:  false        // true = 只画一帧静止画面
  };

  /* 深色预设：?bg=dark 时自动套用（QQ 下载页那种深蓝紫） */
  var DARK_PRESET = {
    lightness: 0.34, saturation: 0.70, bandStrength: 0.85, baseHue: 0.60, grain: 0.02
  };

  /* =========================================================
     模式解析：?bg=static | none | dark | on
     ========================================================= */
  var LS_KEY = 'jf_bg';
  var mode = '';
  try {
    var m = new URLSearchParams(location.search).get('bg');
    if (m) { mode = m.toLowerCase(); localStorage.setItem(LS_KEY, mode); }
    else { mode = (localStorage.getItem(LS_KEY) || '').toLowerCase(); }
  } catch (e) {}

  var root = document.documentElement;
  if (mode === 'static') { CFG.static = true; root.classList.add('bg-static'); }
  if (mode === 'none')   { CFG.enabled = false; root.classList.add('bg-none'); }
  if (mode === 'dark')   { root.classList.add('bg-dark'); for (var k in DARK_PRESET) CFG[k] = DARK_PRESET[k]; }

  var reduceMQ = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
  var reduceMotion = !!(reduceMQ && reduceMQ.matches);

  /* =========================================================
     画布准备
     ========================================================= */
  var cv = document.getElementById('liquid-bg');
  if (!cv) { cv = document.createElement('canvas'); cv.id = 'liquid-bg'; document.body.insertBefore(cv, document.body.firstChild); }
  var fx = document.getElementById('bg-fx');
  if (!fx) { fx = document.createElement('canvas'); fx.id = 'bg-fx'; document.body.insertBefore(fx, cv.nextSibling); }

  if (!CFG.enabled) { cv.style.display = 'none'; fx.style.display = 'none'; }

  var ctx2d = fx.getContext('2d');
  var gl = null;
  try { gl = cv.getContext('webgl', { antialias: false, alpha: false, depth: false, powerPreference: 'low-power' })
           || cv.getContext('experimental-webgl'); } catch (e) {}
  if (!gl) document.body.classList.add('no-webgl'); // CSS 里已备好静态渐变兜底

  /* =========================================================
     着色器
     ========================================================= */
  var VS = 'attribute vec2 p;void main(){gl_Position=vec4(p,0.0,1.0);}';
  var FS = [
    'precision highp float;',
    'uniform vec2 u_res; uniform float u_time; uniform float u_aspect;',
    'uniform float u_hueSpeed,u_sat,u_light,u_flow,u_bands,u_strength,u_warp,u_spread,u_baseHue,u_grain;',
    'uniform float u_rSpeed,u_rLife,u_rGlow;',
    'uniform vec4 u_clicks[8];', // xy=归一化坐标 z=起始时间 w=强度
    'vec3 hsl2rgb(vec3 c){',
    '  vec3 k=clamp(abs(mod(c.x*6.0+vec3(0.0,4.0,2.0),6.0)-3.0)-1.0,0.0,1.0);',
    '  return c.z + c.y*(k-0.5)*(1.0-abs(2.0*c.z-1.0));}',
    'float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}',
    'float noise(vec2 p){vec2 i=floor(p),f=fract(p);',
    '  float a=hash(i),b=hash(i+vec2(1.,0.)),c=hash(i+vec2(0.,1.)),d=hash(i+vec2(1.,1.));',
    '  vec2 u=f*f*(3.0-2.0*f);return mix(mix(a,b,u.x),mix(c,d,u.x),u.y);}',
    'float fbm(vec2 p){float v=0.0,a=0.5;for(int i=0;i<5;i++){v+=a*noise(p);p*=2.03;a*=0.5;}return v;}',
    'void main(){',
    '  vec2 uv=gl_FragCoord.xy/u_res;',
    '  vec2 p=(uv-0.5)*vec2(u_aspect,1.0)*2.2;',
    '  float t=u_time*u_flow;',
    /* domain warping：两层扭曲 = 液体般的光带 */
    '  vec2 q=vec2(fbm(p+vec2(0.0,t)),fbm(p+vec2(3.4,1.7)-t*0.7));',
    '  vec2 r=vec2(fbm(p+u_warp*q+vec2(1.7,9.2)+t*0.5),fbm(p+u_warp*q+vec2(8.3,2.8)-t*0.35));',
    '  float f=fbm(p+u_warp*r);',
    /* 光带：正弦条带，随时间平滑漂移 */
    '  float band=0.5+0.5*sin(6.28318*(f*u_bands+t*0.6));',
    '  band=pow(band,1.5);',
    /* 色相循环：fract 保证首尾相接，绝不跳色 */
    '  float hue=u_baseHue+u_time*u_hueSpeed+f*u_spread+band*0.04;',
    '  float lig=u_light+(band-0.5)*0.10;',
    '  vec3 col=hsl2rgb(vec3(fract(hue),u_sat,clamp(lig,0.03,0.97)));',
    /* 与页面底色融合：越靠近光带中心越浓，其余留白 → 文字永远有干净底 */
    '  vec3 base=vec3(0.992,0.988,0.973);',
    '  col=mix(base,col,u_strength*(0.30+0.70*band));',
    /* 点击涟漪 */
    '  for(int i=0;i<8;i++){',
    '    vec4 c=u_clicks[i];',
    '    if(c.w<=0.0) continue;',
    '    float age=u_time-c.z;',
    '    if(age<0.0||age>u_rLife) continue;',
    '    vec2 d=(uv-c.xy)*vec2(u_aspect,1.0);',
    '    float dist=length(d);',
    '    float rad=age*u_rSpeed;',
    '    float ring=exp(-pow((dist-rad)*13.0,2.0))*(1.0-age/u_rLife);',
    '    col+=ring*c.w*u_rGlow*(0.55+0.45*hsl2rgb(vec3(fract(hue+0.12),u_sat,0.62)));',
    '  }',
    /* 轻微暗角 + 颗粒：消除大面积渐变的色带断层 */
    '  float vig=1.0-0.18*dot(uv-0.5,uv-0.5);',
    '  col*=vig;',
    '  col+=(hash(gl_FragCoord.xy+u_time)-0.5)*u_grain;',
    '  gl_FragColor=vec4(clamp(col,0.0,1.0),1.0);}'
  ].join('\n');

  var prog = null, U = {}, DPR = 1, RS = CFG.resolutionScale;

  function compile(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.warn('[bg] shader:', gl.getShaderInfoLog(s)); return null; }
    return s;
  }

  function initGL() {
    var v = compile(gl.VERTEX_SHADER, VS), f = compile(gl.FRAGMENT_SHADER, FS);
    if (!v || !f) return false;
    prog = gl.createProgram();
    gl.attachShader(prog, v); gl.attachShader(prog, f); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.warn('[bg] link:', gl.getProgramInfoLog(prog)); return false; }
    gl.useProgram(prog);
    var b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    ['u_res','u_time','u_aspect','u_hueSpeed','u_sat','u_light','u_flow','u_bands','u_strength',
     'u_warp','u_spread','u_baseHue','u_grain','u_rSpeed','u_rLife','u_rGlow']
      .forEach(function (n) { U[n] = gl.getUniformLocation(prog, n); });
    U.u_clicks = gl.getUniformLocation(prog, 'u_clicks') || gl.getUniformLocation(prog, 'u_clicks[0]');
    return true;
  }

  /* =========================================================
     尺寸自适应（含移动端 100dvh / 旋屏 / 缩放）
     ========================================================= */
  var W = 0, H = 0;
  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 1.5);
    var w = window.innerWidth, h = window.innerHeight;
    W = w; H = h;
    if (gl) { cv.width = Math.max(1, Math.floor(w * DPR * RS)); cv.height = Math.max(1, Math.floor(h * DPR * RS)); gl.viewport(0, 0, cv.width, cv.height); }
    fx.width = Math.max(1, Math.floor(w * DPR)); fx.height = Math.max(1, Math.floor(h * DPR));
    fx.style.width = w + 'px'; fx.style.height = h + 'px';
    if (ctx2d) ctx2d.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  var rzTimer;
  window.addEventListener('resize', function () { clearTimeout(rzTimer); rzTimer = setTimeout(resize, 120); });
  window.addEventListener('orientationchange', function () { setTimeout(resize, 250); });

  /* =========================================================
     点击：涟漪（着色器）+ 粒子扩散（2D）
     ========================================================= */
  var clicks = [];                 // {x,y,t,s}  归一化坐标
  var clickBuf = new Float32Array(8 * 4);
  var parts = [];                  // 粒子
  var clock = 0;                   // 动画时钟（秒，暂停时不走）

  function spawn(x, y) {
    if (CFG.ripple && gl && !CFG.static && !reduceMotion) {
      clicks.push({ x: x / W, y: 1 - y / H, t: clock, s: 1 });
      if (clicks.length > CFG.maxRipples) clicks.shift();
    }
    if (CFG.particles && ctx2d && !CFG.static && !reduceMotion) {
      var hue = ((CFG.baseHue + clock * CFG.hueSpeed) % 1) * 360;
      for (var i = 0; i < CFG.particleCount; i++) {
        var a = (Math.PI * 2 * i) / CFG.particleCount + Math.random() * 0.5;
        var sp = CFG.particleSpeed * (0.45 + Math.random() * 0.75);
        parts.push({
          x: x, y: y,
          vx: Math.cos(a) * sp, vy: Math.sin(a) * sp,
          life: 0, max: CFG.particleLife * (0.7 + Math.random() * 0.6),
          r: CFG.particleSize * (0.6 + Math.random() * 0.9),
          h: (hue + Math.random() * 40 - 20 + 360) % 360
        });
      }
      if (parts.length > 260) parts.splice(0, parts.length - 260);
    }
  }

  window.addEventListener('pointerdown', function (e) {
    spawn(e.clientX, e.clientY);   // passive 监听，绝不阻止按钮/链接的默认行为
  }, { passive: true });

  function drawParticles(dt) {
    if (!ctx2d) return;
    ctx2d.clearRect(0, 0, W, H);
    for (var i = parts.length - 1; i >= 0; i--) {
      var p = parts[i];
      p.life += dt;
      if (p.life >= p.max) { parts.splice(i, 1); continue; }
      p.x += p.vx * dt; p.y += p.vy * dt;
      p.vx *= 0.965; p.vy *= 0.965; p.vy += 26 * dt;      // 阻尼 + 轻微下坠
      var k = 1 - p.life / p.max;
      ctx2d.beginPath();
      ctx2d.globalAlpha = Math.max(0, k * k * 0.85);
      ctx2d.fillStyle = 'hsl(' + p.h.toFixed(0) + ',' + Math.round(CFG.saturation * 100) + '%,' + Math.round(Math.min(0.82, CFG.lightness + 0.06) * 100) + '%)';
      ctx2d.arc(p.x, p.y, p.r * (0.4 + k), 0, 6.2832);
      ctx2d.fill();
    }
    ctx2d.globalAlpha = 1;
  }

  /* =========================================================
     主循环（含后台暂停 / 帧率上限）
     ========================================================= */
  var raf = 0, last = 0, running = false, t0 = 0;

  function frame(now) {
    raf = requestAnimationFrame(frame);
    var dt = (now - last) / 1000;
    if (dt < 1 / CFG.maxFps - 0.001) return;   // 帧率上限（高刷屏不会白跑）
    last = now;
    dt = Math.min(0.05, dt);
    clock += dt;

    if (gl && prog) {
      gl.uniform2f(U.u_res, cv.width, cv.height);
      gl.uniform1f(U.u_time, clock);
      gl.uniform1f(U.u_aspect, W / H);
      gl.uniform1f(U.u_hueSpeed, CFG.hueSpeed);
      gl.uniform1f(U.u_sat, CFG.saturation);
      gl.uniform1f(U.u_light, CFG.lightness);
      gl.uniform1f(U.u_flow, CFG.flowSpeed);
      gl.uniform1f(U.u_bands, CFG.bandCount);
      gl.uniform1f(U.u_strength, CFG.bandStrength);
      gl.uniform1f(U.u_warp, CFG.warp);
      gl.uniform1f(U.u_spread, CFG.hueSpread);
      gl.uniform1f(U.u_baseHue, CFG.baseHue);
      gl.uniform1f(U.u_grain, CFG.grain);
      gl.uniform1f(U.u_rSpeed, CFG.rippleSpeed);
      gl.uniform1f(U.u_rLife, CFG.rippleLife);
      gl.uniform1f(U.u_rGlow, CFG.rippleGlow);

      clickBuf.fill(0);
      for (var i = 0; i < clicks.length && i < 8; i++) {
        var c = clicks[i];
        if (clock - c.t > CFG.rippleLife) continue;
        clickBuf[i * 4] = c.x; clickBuf[i * 4 + 1] = c.y; clickBuf[i * 4 + 2] = c.t; clickBuf[i * 4 + 3] = c.s;
      }
      if (U.u_clicks) gl.uniform4fv(U.u_clicks, clickBuf);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    drawParticles(dt);
  }

  function start() {
    if (running || !CFG.enabled || CFG.static || reduceMotion) return;
    running = true; last = performance.now();
    raf = requestAnimationFrame(frame);
  }
  function stop() {
    running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }
  /* 切到后台立刻停，回来再跑（省电、不烧 GPU） */
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stop(); else start();
  });
  window.addEventListener('pagehide', stop);
  window.addEventListener('blur', function () { if (document.hidden) stop(); });

  /* =========================================================
     启动
     ========================================================= */
  function boot() {
    resize();
    if (!CFG.enabled) return;
    if (gl && !initGL()) gl = null;

    if (CFG.static || reduceMotion || !gl) {
      // 只画一帧静止画面：保留配色，去掉一切运动
      if (gl && prog) { renderOnce(); }
      else if (gl && !prog) { document.body.classList.add('no-webgl'); }
      return;
    }
    start();
  }

  function renderOnce() {
    gl.uniform2f(U.u_res, cv.width, cv.height);
    gl.uniform1f(U.u_time, 12.0);                 // 固定时刻 = 静止的一帧
    gl.uniform1f(U.u_aspect, W / H);
    gl.uniform1f(U.u_hueSpeed, 0);
    gl.uniform1f(U.u_sat, CFG.saturation);
    gl.uniform1f(U.u_light, CFG.lightness);
    gl.uniform1f(U.u_flow, CFG.flowSpeed);
    gl.uniform1f(U.u_bands, CFG.bandCount);
    gl.uniform1f(U.u_strength, CFG.bandStrength);
    gl.uniform1f(U.u_warp, CFG.warp);
    gl.uniform1f(U.u_spread, CFG.hueSpread);
    gl.uniform1f(U.u_baseHue, CFG.baseHue);
    gl.uniform1f(U.u_grain, CFG.grain);
    gl.uniform1f(U.u_rSpeed, CFG.rippleSpeed);
    gl.uniform1f(U.u_rLife, CFG.rippleLife);
    gl.uniform1f(U.u_rGlow, 0);
    clickBuf.fill(0);
    if (U.u_clicks) gl.uniform4fv(U.u_clicks, clickBuf);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();

  /* =========================================================
     对外 API：控制台里随手调
       JuFangBG.set('hueSpeed', 0.12)    改单个参数，立即生效
       JuFangBG.setStatic(true/false)    一键切静态背景
       JuFangBG.pause() / resume()
     ========================================================= */
  window.JuFangBG = {
    config: CFG,
    set: function (k, v) { if (k in CFG) { CFG[k] = v; resize(); } return CFG; },
    setStatic: function (on) {
      CFG.static = !!on;
      root.classList.toggle('bg-static', !!on);
      try { localStorage.setItem(LS_KEY, on ? 'static' : 'on'); } catch (e) {}
      if (on) { stop(); if (ctx2d) ctx2d.clearRect(0, 0, W, H); if (gl && prog) renderOnce(); }
      else { start(); }
    },
    pause: stop,
    resume: start,
    isRunning: function () { return running; }
  };

  /* 系统「减弱动态效果」开关被中途改动时，实时响应 */
  if (reduceMQ && reduceMQ.addEventListener) {
    reduceMQ.addEventListener('change', function (e) {
      reduceMotion = e.matches;
      if (reduceMotion) { stop(); if (ctx2d) ctx2d.clearRect(0, 0, W, H); if (gl && prog) renderOnce(); }
      else start();
    });
  }
})();
