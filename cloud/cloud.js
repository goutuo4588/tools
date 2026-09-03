// 工具铺后端云函数（腾讯云 CloudBase 云函数 Node 运行）
// 完整账号后端：注册发验证码 / 校验验证码并建号 / 登录 / 忘记密码通知站长 / 站长列用户 / 站长重置密码
// 通过「HTTP 访问服务」暴露，前端用 fetch 调用，绕过免费版 WEB 安全域名锁。
// 环境变量（云函数环境变量中配置）：
//   SMTP_USER    163 邮箱，如 goutuoshigesha@163.com
//   SMTP_PASS    163 邮箱 SMTP 授权码（不是登录密码）
//   OWNER_EMAIL  接收找回密码申请的邮箱，默认 goutuoshigesha@163.com
//   ADMIN_PWD    站长后台密码（与前端 index.html 里的 ADMIN_PWD 一致）
// 数据库集合：tp_users（账号）、tp_codes（邮箱验证码，5 分钟过期）

const cloudbase = require('@cloudbase/node-sdk');
const nodemailer = require('nodemailer');
const crypto = require('crypto');

const app = cloudbase.init({});
const db = app.database();

const ALLOW_ORIGIN = 'https://goutuo4588.github.io';
const CORS = {
  'Access-Control-Allow-Origin': ALLOW_ORIGIN,
  'Access-Control-Allow-Methods': 'POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Content-Type': 'application/json'
};

function transporter() {
  return nodemailer.createTransport({
    host: 'smtp.163.com',
    port: 465,
    secure: true,
    auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS }
  });
}

function ok(body) { return { statusCode: 200, headers: CORS, body: JSON.stringify(body || {}) }; }
function preflight() { return { statusCode: 204, headers: CORS, body: '' }; }

function hashPassword(pwd) {
  const salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(pwd, salt, 64).toString('hex');
  return { salt, hash };
}
function verifyPassword(pwd, salt, hash) {
  if (!salt || !hash) return false;
  const h = crypto.scryptSync(pwd, salt, 64).toString('hex');
  try { return crypto.timingSafeEqual(Buffer.from(h, 'hex'), Buffer.from(hash, 'hex')); }
  catch (e) { return false; }
}

async function sendCode(email) {
  const code = String(Math.floor(100000 + Math.random() * 900000));
  const expire = Date.now() + 5 * 60 * 1000;
  await db.collection('tp_codes').where({ email }).remove().catch(function () {});
  await db.collection('tp_codes').add({ email: email, code: code, expire: expire });
  await transporter().sendMail({
    from: process.env.SMTP_USER,
    to: email,
    subject: '[工具铺] 邮箱验证码',
    text: '你的注册验证码是：' + code + '\n5 分钟内有效，请勿泄露给他人。如非本人操作请忽略。'
  });
  return code;
}

exports.main = async (event) => {
  // 判断是否为 HTTP 触发（云函数 HTTP 访问服务）
  const isHttp = !!(event && (event.httpMethod || event.requestContext || (event.headers && event.headers.host)));
  let payload = event;
  if (isHttp) {
    if (event.httpMethod === 'OPTIONS') return preflight();
    try {
      const raw = (typeof event.body === 'string') ? event.body : (event.body || '{}');
      payload = JSON.parse(raw);
    } catch (e) { return ok({ code: 400, error: '请求体解析失败' }); }
  }
  const action = payload && payload.action;
  const now = Date.now();

  // 注册：发送邮箱验证码
  if (action === 'register') {
    const email = (payload.email || '').trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return ok({ code: 400, error: '邮箱格式不正确' });
    try {
      const ex = await db.collection('tp_users').where({ email }).get();
      if (ex.data && ex.data.length) return ok({ code: 409, error: '该邮箱已注册，请直接登录' });
      await sendCode(email);
      return ok({ code: 0, message: '验证码已发送，请查收邮箱' });
    } catch (e) { return ok({ code: 500, error: '发送失败：' + (e.message || String(e)) }); }
  }

  // 校验验证码并创建账号（密码服务端哈希）
  if (action === 'verifyRegister') {
    const email = (payload.email || '').trim().toLowerCase();
    const code = (payload.code || '').trim();
    const pwd = payload.password || '';
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return ok({ code: 400, error: '邮箱格式不正确' });
    if (!/^(?=.*[a-zA-Z])(?=.*\d).{8,32}$/.test(pwd)) return ok({ code: 400, error: '密码需 8-32 位且含字母和数字' });
    try {
      const c = await db.collection('tp_codes').where({ email }).get();
      const rec = c.data && c.data[0];
      if (!rec) return ok({ code: 400, error: '请先获取验证码' });
      if (rec.expire < Date.now()) return ok({ code: 400, error: '验证码已过期，请重新获取' });
      if (rec.code !== code) return ok({ code: 400, error: '验证码错误' });
      const hp = hashPassword(pwd);
      await db.collection('tp_users').add({
        email: email, salt: hp.salt, passwordHash: hp.hash, createdAt: now, lastLogin: now
      });
      await db.collection('tp_codes').doc(rec._id).remove().catch(function () {});
      return ok({ code: 0, uid: email });
    } catch (e) { return ok({ code: 500, error: '注册失败：' + (e.message || String(e)) }); }
  }

  // 登录：校验邮箱 + 密码
  if (action === 'login') {
    const email = (payload.email || '').trim().toLowerCase();
    const pwd = payload.password || '';
    try {
      const u = await db.collection('tp_users').where({ email }).get();
      const rec = u.data && u.data[0];
      if (!rec) return ok({ code: 401, error: '邮箱或密码错误' });
      if (!verifyPassword(pwd, rec.salt, rec.passwordHash)) return ok({ code: 401, error: '邮箱或密码错误' });
      await db.collection('tp_users').doc(rec._id).update({ lastLogin: Date.now() }).catch(function () {});
      return ok({ code: 0, uid: email });
    } catch (e) { return ok({ code: 500, error: '登录失败：' + (e.message || String(e)) }); }
  }

  // 忘记密码：把申请邮件发给站长（不发旧密码）
  if (action === 'requestPasswordHelp') {
    const email = (payload.email || '').trim().toLowerCase();
    if (!email) return ok({ code: 400, error: '请输入邮箱' });
    let exists = false;
    try { const u = await db.collection('tp_users').where({ email }).get(); exists = !!(u.data && u.data.length); } catch (e) {}
    try {
      await transporter().sendMail({
        from: process.env.SMTP_USER,
        to: process.env.OWNER_EMAIL || 'goutuoshigesha@163.com',
        subject: '[工具铺] 用户找回密码申请',
        text: '有用户申请找回密码。\n\n邮箱：' + email + '\n账号是否存在：' + (exists ? '是' : '否（可能是未注册邮箱）') + '\n申请时间：' + new Date().toLocaleString('zh-CN') + '\n'
      });
    } catch (e) { return ok({ code: 500, error: '邮件发送失败：' + (e.message || String(e)) }); }
    return ok({ code: 0, message: '已提交给站长，请耐心等待站长协助你重置密码。' });
  }

  // 站长：列出全部注册用户
  if (action === 'adminListUsers') {
    if (payload.adminPwd !== process.env.ADMIN_PWD) return ok({ code: 401, error: '无权限' });
    try {
      const res = await db.collection('tp_users').limit(1000).get();
      return ok({ code: 0, result: (res.data || []).map(function (u) {
        return { email: u.email, createdAt: u.createdAt, lastLogin: u.lastLogin };
      }) });
    } catch (e) { return ok({ code: 500, error: e.message || String(e) }); }
  }

  // 站长：重置某用户密码（服务端哈希后写入，并邮件通知用户）
  if (action === 'adminResetPassword') {
    if (payload.adminPwd !== process.env.ADMIN_PWD) return ok({ code: 401, error: '无权限' });
    const email = (payload.email || '').trim().toLowerCase();
    const np = payload.newPwd || '';
    if (!email || !np) return ok({ code: 400, error: '参数缺失' });
    if (!/^(?=.*[a-zA-Z])(?=.*\d).{8,32}$/.test(np)) return ok({ code: 400, error: '新密码需 8-32 位且含字母和数字' });
    try {
      const u = await db.collection('tp_users').where({ email }).get();
      const rec = u.data && u.data[0];
      if (!rec) return ok({ code: 404, error: '用户不存在' });
      const hp = hashPassword(np);
      await db.collection('tp_users').doc(rec._id).update({ salt: hp.salt, passwordHash: hp.hash }).catch(function () {});
      try {
        await transporter().sendMail({
          from: process.env.SMTP_USER,
          to: email,
          subject: '[工具铺] 密码已重置',
          text: '你的密码已被站长重置为：' + np + '\n请尽快登录并修改密码。'
        });
      } catch (e) {}
      return ok({ code: 0, message: 'ok' });
    } catch (e) { return ok({ code: 500, error: e.message || String(e) }); }
  }

  return ok({ code: 404, error: 'unknown action' });
};
