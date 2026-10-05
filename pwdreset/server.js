'use strict';
const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const tls = require('tls');

// ============ 配置 ============
const PORT = process.env.PORT || 3000;
const ADMIN_PASS = process.env.ADMIN_PASS || 'admin123'; // 部署务必改成强密码！
const ADMIN_HASH = crypto.createHash('sha256').update(ADMIN_PASS).digest('hex');
const MAIL_USER = process.env.MAIL_USER || '';
const MAIL_PASS = process.env.MAIL_PASS || '';      // 163 邮箱授权码
const MAIL_FROM = process.env.MAIL_FROM || MAIL_USER;
const SESSION_TTL = 7 * 24 * 3600 * 1000;          // 管理员会话 7 天
const PUBLIC_DIR = path.join(__dirname, 'public');
const DATA_DIR = path.join(__dirname, 'data');
fs.mkdirSync(DATA_DIR, { recursive: true });

// ============ 存储（JSON 文件，零依赖）============
function loadJson(name, def) {
  const f = path.join(DATA_DIR, name);
  try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return def; }
}
function saveJson(name, data) {
  const f = path.join(DATA_DIR, name);
  const tmp = f + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, f); // 原子写，避免半截文件
}
let customers = loadJson('customers.json', []);
let requests = loadJson('requests.json', []);
const sessions = new Map();   // token -> {createdAt}
const captchas = new Map();   // id -> {text, exp}
const rateLimit = new Map();  // key -> [timestamps]

// ============ 工具函数 ============
function hashPassword(pw) {
  const salt = crypto.randomBytes(16);
  const d = crypto.scryptSync(pw, salt, 64);
  return salt.toString('hex') + ':' + d.toString('hex');
}
function verifyPassword(pw, stored) {
  try {
    const [s, h] = stored.split(':');
    const d = crypto.scryptSync(pw, Buffer.from(s, 'hex'), 64);
    return crypto.timingSafeEqual(d, Buffer.from(h, 'hex'));
  } catch { return false; }
}
// 12 位随机密码：大小写字母 + 数字，并保证三类都至少出现一次
function genPassword(n = 12) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = crypto.randomBytes(n);
  let out = '';
  for (let i = 0; i < n; i++) out += chars[bytes[i] % chars.length];
  if (!/[A-Z]/.test(out)) out = out.slice(0, -1) + 'A';
  if (!/[a-z]/.test(out)) out = out.slice(0, -1) + 'a';
  if (!/[0-9]/.test(out)) out = out.slice(0, -1) + '3';
  return out;
}
function newToken() { return crypto.randomBytes(24).toString('hex'); }
function parseCookies(req) {
  const h = req.headers.cookie || '';
  const o = {};
  h.split(';').forEach(p => { const i = p.indexOf('='); if (i > 0) o[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim()); });
  return o;
}
function isAdmin(req) {
  const c = parseCookies(req);
  const s = sessions.get(c.sid);
  return s && (Date.now() - s.createdAt) < SESSION_TTL;
}
// 图形验证码（SVG，零依赖）
function genCaptcha() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
  let text = '';
  for (let i = 0; i < 5; i++) text += chars[Math.floor(Math.random() * chars.length)];
  const id = crypto.randomBytes(8).toString('hex');
  const colors = ['#ff7a59', '#5b8def', '#2bb673', '#9b5de5'];
  let svg = '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="44" viewBox="0 0 120 44">';
  svg += '<rect width="120" height="44" rx="8" fill="#f3f4f8"/>';
  for (let i = 0; i < text.length; i++) {
    const x = 14 + i * 20, y = 30 + (Math.random() * 6 - 3), rot = (Math.random() * 40 - 20).toFixed(1);
    const col = colors[i % colors.length];
    svg += `<text x="${x}" y="${y}" font-size="26" font-family="monospace" font-weight="bold" fill="${col}" transform="rotate(${rot} ${x} ${y})">${text[i]}</text>`;
  }
  for (let i = 0; i < 4; i++) {
    svg += `<line x1="${Math.random() * 120}" y1="${Math.random() * 44}" x2="${Math.random() * 120}" y2="${Math.random() * 44}" stroke="#d8dbe6" stroke-width="1"/>`;
  }
  svg += '</svg>';
  captchas.set(id, { text, exp: Date.now() + 5 * 60 * 1000 });
  return { id, svg };
}

// ============ 163 SMTP 发信（零依赖，原生 TLS）============
function sendMail(to, subject, text) {
  if (!MAIL_USER || !MAIL_PASS) {
    console.log('[mail-simulated] to=' + to + ' subject=' + subject + '\n' + text);
    return Promise.resolve({ ok: true, simulated: true });
  }
  return new Promise((resolve, reject) => {
    const sock = tls.connect({ host: 'smtp.163.com', port: 465, timeout: 20000 }, () => {});
    let buf = ''; const waiters = [];
    sock.on('data', d => {
      buf += d.toString('latin1');
      let i;
      while ((i = buf.indexOf('\r\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (waiters.length) waiters.shift()(line);
      }
    });
    sock.on('error', e => reject(e));
    sock.setTimeout(20000, () => { try { sock.destroy(); } catch {} reject(new Error('smtp timeout')); });
    const resp = () => new Promise(r => waiters.push(r));
    const send = async (cmd) => { sock.write(cmd + '\r\n'); return resp(); };
    (async () => {
      try {
        let r = await resp();
        if (!r.startsWith('220')) throw new Error('banner ' + r);
        r = await send('EHLO localhost');
        while (r.startsWith('250-')) r = await resp();
        if (!r.startsWith('250')) throw new Error('ehlo ' + r);
        r = await send('AUTH LOGIN');
        if (!r.startsWith('334')) throw new Error('auth ' + r);
        r = await send(Buffer.from(MAIL_USER).toString('base64'));
        if (!r.startsWith('334')) throw new Error('user ' + r);
        r = await send(Buffer.from(MAIL_PASS).toString('base64'));
        if (!r.startsWith('235')) throw new Error('pass ' + r);
        r = await send('MAIL FROM:<' + MAIL_FROM + '>');
        if (!r.startsWith('250')) throw new Error('mailfrom ' + r);
        r = await send('RCPT TO:<' + to + '>');
        if (!r.startsWith('250')) throw new Error('rcpt ' + r);
        r = await send('DATA');
        if (!r.startsWith('354')) throw new Error('data ' + r);
        const headers = [
          'From: ' + MAIL_FROM,
          'To: ' + to,
          'Subject: =?UTF-8?B?' + Buffer.from(subject).toString('base64') + '?=',
          'Date: ' + new Date().toUTCString(),
          'MIME-Version: 1.0',
          'Content-Type: text/plain; charset=UTF-8',
          ''
        ];
        for (const l of headers) sock.write(l + '\r\n');
        for (const l of text.split('\r\n')) sock.write(l + '\r\n');
        r = await send('.');
        if (!r.startsWith('250')) throw new Error('body ' + r);
        await send('QUIT');
        sock.end();
        resolve({ ok: true });
      } catch (e) { try { sock.destroy(); } catch {} reject(e); }
    })();
  });
}
function mailBody(customerName, newPw) {
  return `尊敬的 ${customerName} 您好：

应您的密码找回申请，我们已将您的账户密码重置为以下随机密码：

    ${newPw}

（该密码由 12 位大小写字母与数字组成，请登录后尽快修改为您的个人密码。）

如非本人操作，请忽略本邮件并及时联系管理员。

—— 具坊密码重置服务`;
}

// ============ HTTP 辅助 ============
function sendJson(res, code, obj, extraHeaders) {
  const body = JSON.stringify(obj);
  res.writeHead(code, Object.assign({ 'Content-Type': 'application/json; charset=utf-8' }, extraHeaders || {}));
  res.end(body);
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    let d = '';
    req.on('data', c => { d += c; if (d.length > 1e6) req.destroy(); });
    req.on('end', () => { try { resolve(d ? JSON.parse(d) : {}); } catch { reject(new Error('bad json')); } });
    req.on('error', reject);
  });
}
const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.png': 'image/png' };
function serveStatic(res, urlPath) {
  let rel = urlPath === '/' ? '/index.html' : urlPath;
  if (rel === '/register') rel = '/register.html';
  if (rel === '/admin') rel = '/admin.html';
  const fp = path.join(PUBLIC_DIR, path.normalize(rel).replace(/^(\.\.[/\\])+/, ''));
  if (!fp.startsWith(PUBLIC_DIR)) { res.writeHead(403); res.end('forbidden'); return; }
  fs.readFile(fp, (err, data) => {
    if (err) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream' });
    res.end(data);
  });
}
// 限频：同 email+username 60s 内 1 次；同 IP 当日最多 30 次
function checkRate(key, ip) {
  const now = Date.now();
  const arr = (rateLimit.get(key) || []).filter(t => now - t < 60000);
  rateLimit.set(key, arr);
  if (arr.length >= 1) return '操作太频繁，请 1 分钟后再试';
  const dayKey = 'day:' + ip + ':' + new Date().toDateString();
  const dayArr = (rateLimit.get(dayKey) || []).filter(t => now - t < 86400000);
  if (dayArr.length >= 30) return '今日申请次数过多，请明天再试';
  arr.push(now); rateLimit.set(key, arr); dayArr.push(now); rateLimit.set(dayKey, dayArr);
  return null;
}

// ============ 路由 ============
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://localhost');
  const p = u.pathname;
  try {
    // 验证码图片
    if (p === '/api/captcha' && req.method === 'GET') {
      const { id, svg } = genCaptcha();
      res.writeHead(200, { 'Content-Type': 'image/svg+xml', 'Set-Cookie': 'capid=' + id + '; HttpOnly; Path=/; Max-Age=300' });
      res.end(svg); return;
    }
    // 客户注册
    if (p === '/api/register' && req.method === 'POST') {
      const b = await readBody(req);
      if (!b.username || !b.email || !b.password) return sendJson(res, 400, { error: '用户名、邮箱、密码必填' });
      if (!/^[A-Za-z0-9_]{3,20}$/.test(b.username)) return sendJson(res, 400, { error: '用户名需 3-20 位字母/数字/下划线' });
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(b.email)) return sendJson(res, 400, { error: '邮箱格式不正确' });
      if (b.password.length < 6) return sendJson(res, 400, { error: '密码至少 6 位' });
      if (customers.find(c => c.username === b.username)) return sendJson(res, 400, { error: '用户名已存在' });
      if (customers.find(c => c.email === b.email)) return sendJson(res, 400, { error: '邮箱已注册' });
      customers.push({ id: newToken(), username: b.username, email: b.email, password: hashPassword(b.password), createdAt: Date.now() });
      saveJson('customers.json', customers);
      return sendJson(res, 200, { ok: true, msg: '注册成功' });
    }
    // 申请找回（公开，验证码 + 限频；不泄露账号是否存在）
    if (p === '/api/request-reset' && req.method === 'POST') {
      const b = await readBody(req);
      if (!b.username || !b.email || !b.captcha) return sendJson(res, 400, { error: '请填写完整' });
      const ip = req.socket.remoteAddress || 'unknown';
      const rl = checkRate(b.email + '|' + b.username, ip);
      if (rl) return sendJson(res, 429, { error: rl });
      const c = parseCookies(req);
      const cap = captchas.get(c.capid);
      if (!cap || cap.exp < Date.now()) return sendJson(res, 400, { error: '验证码已过期，请刷新' });
      if (cap.text.toLowerCase() !== String(b.captcha).toLowerCase()) return sendJson(res, 400, { error: '验证码错误' });
      captchas.delete(c.capid);
      const cust = customers.find(x => x.username === b.username && x.email === b.email);
      requests.push({ id: newToken(), customerId: cust ? cust.id : null, username: b.username, email: b.email, status: 'pending', createdAt: Date.now() });
      saveJson('requests.json', requests);
      return sendJson(res, 200, { ok: true, msg: '申请已提交，管理员处理后将以邮件发送新密码' });
    }
    // 管理员登录
    if (p === '/api/admin/login' && req.method === 'POST') {
      const b = await readBody(req);
      if (crypto.createHash('sha256').update(b.password || '').digest('hex') === ADMIN_HASH) {
        const t = newToken(); sessions.set(t, { createdAt: Date.now() });
        return sendJson(res, 200, { ok: true }, { 'Set-Cookie': 'sid=' + t + '; HttpOnly; Path=/; Max-Age=' + (SESSION_TTL / 1000) });
      }
      return sendJson(res, 401, { error: '密码错误' });
    }
    // 管理员登录态
    if (p === '/api/admin/me' && req.method === 'GET') {
      return sendJson(res, 200, { admin: isAdmin(req) });
    }
    // 查看申请队列（需登录）
    if (p === '/api/admin/requests' && req.method === 'GET') {
      if (!isAdmin(req)) return sendJson(res, 401, { error: '未登录' });
      const pending = requests.filter(r => r.status === 'pending').sort((a, b) => b.createdAt - a.createdAt);
      const done = requests.filter(r => r.status !== 'pending').slice(-20).reverse();
      return sendJson(res, 200, { pending, done });
    }
    // 一键重置（需登录）：生成 12 位随机密码 -> 更新客户 -> 发邮件 -> 标记完成（密码不落盘、不回显）
    if (p.startsWith('/api/admin/reset/') && req.method === 'POST') {
      if (!isAdmin(req)) return sendJson(res, 401, { error: '未登录' });
      const id = p.split('/').pop();
      const item = requests.find(r => r.id === id && r.status === 'pending');
      if (!item) return sendJson(res, 404, { error: '申请不存在或已处理' });
      const cust = item.customerId ? customers.find(c => c.id === item.customerId) : null;
      if (!cust) return sendJson(res, 400, { error: '该申请无匹配客户账号（用户名/邮箱不匹配）' });
      const newPw = genPassword(12);
      cust.password = hashPassword(newPw);
      saveJson('customers.json', customers);
      item.status = 'done'; item.resetAt = Date.now();
      saveJson('requests.json', requests);
      const mail = await sendMail(cust.email, '您的账户密码已重置', mailBody(cust.username, newPw));
      return sendJson(res, 200, { ok: true, email: cust.email, simulated: !!mail.simulated });
    }
    // 静态资源
    if (req.method === 'GET' && !p.startsWith('/api/')) { serveStatic(res, p); return; }
    sendJson(res, 404, { error: 'not found' });
  } catch (e) {
    console.error(e);
    sendJson(res, 500, { error: 'server error' });
  }
});

// 定时清理过期 session / 验证码
setInterval(() => {
  const now = Date.now();
  for (const [k, v] of sessions) if (now - v.createdAt > SESSION_TTL) sessions.delete(k);
  for (const [k, v] of captchas) if (v.exp < now) captchas.delete(k);
}, 60000);

server.listen(PORT, () => console.log('密码重置服务已启动: http://localhost:' + PORT));
