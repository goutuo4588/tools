// 工具铺后端云函数（腾讯云 CloudBase 云函数 Node 运行）
// 部署：在 CloudBase 控制台新建云函数「toolshop」，上传本目录（含 package.json）；或用 CLI: tcb fn deploy toolshop
// 环境变量（云函数环境变量中配置）：
//   SMTP_USER    你的 163 邮箱，如 goutuoshigesha@163.com
//   SMTP_PASS    163 邮箱 SMTP 授权码（不是登录密码）
//   OWNER_EMAIL  接收找回密码申请的邮箱，默认 goutuoshigesha@163.com
//   ADMIN_PWD    站长后台密码（与前端 index.html 里的 ADMIN_PWD 一致）
// 数据库集合 tp_users 会在首次 logLogin 时自动创建（注册/登录由前端同步写入）。

const cloudbase = require('@cloudbase/node-sdk');
const nodemailer = require('nodemailer');

const app = cloudbase.init({});
const db = app.database();
const auth = app.auth();

function transporter() {
  return nodemailer.createTransport({
    host: 'smtp.163.com',
    port: 465,
    secure: true,
    auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS }
  });
}

// 统一入口，按 event.action 分发
exports.main = async (event) => {
  const action = event.action;
  const now = Date.now();

  // 忘记密码：把申请邮件发给站长（不发送旧密码，仅通知）
  if (action === 'requestPasswordHelp') {
    const email = (event.email || '').trim();
    if (!email) return { code: 400, error: '请输入邮箱' };
    let exists = false;
    try {
      const u = await auth.getUserByEmail(email);
      exists = !!u;
    } catch (e) { exists = false; }
    await transporter().sendMail({
      from: process.env.SMTP_USER,
      to: process.env.OWNER_EMAIL || 'goutuoshigesha@163.com',
      subject: '[工具铺] 用户找回密码申请',
      text:
        '有用户申请找回密码，请到 CloudBase 控制台「身份认证 → 用户管理」为其重置密码，并通知用户。\n\n' +
        '邮箱：' + email + '\n' +
        '账号是否存在：' + (exists ? '是' : '否（可能是未注册邮箱）') + '\n' +
        '申请时间：' + new Date().toLocaleString('zh-CN') + '\n'
    });
    return { code: 0, message: 'ok' };
  }

  // 同步用户（注册/登录成功后由前端调用）：写入/更新 tp_users
  if (action === 'logLogin') {
    const email = (event.email || '').trim().toLowerCase();
    if (!email) return { code: 400, error: '缺少邮箱' };
    try {
      const ex = await db.collection('tp_users').where({ email }).get();
      if (ex.data && ex.data.length) {
        await db.collection('tp_users').doc(ex.data[0]._id).update({ lastLogin: now });
      } else {
        await db.collection('tp_users').add({ email, createdAt: now, lastLogin: now });
      }
    } catch (e) { return { code: 500, error: e.message || String(e) }; }
    return { code: 0 };
  }

  // 站长：列出全部注册用户
  if (action === 'adminListUsers') {
    if (event.adminPwd !== process.env.ADMIN_PWD) return { code: 401, error: '无权限' };
    try {
      const res = await db.collection('tp_users').limit(1000).get();
      return { code: 0, result: (res.data || []).map(u => ({
        email: u.email,
        createdAt: u.createdAt,
        lastLogin: u.lastLogin
      })) };
    } catch (e) { return { code: 500, error: e.message || String(e) }; }
  }

  // 站长：重置某用户密码（用 CloudBase admin API 设定新密码，再邮件通知用户）
  if (action === 'adminResetPassword') {
    if (event.adminPwd !== process.env.ADMIN_PWD) return { code: 401, error: '无权限' };
    const email = (event.email || '').trim().toLowerCase();
    const np = event.newPwd || '';
    if (!email || !np) return { code: 400, error: '参数缺失' };
    if (!/^(?=.*[a-zA-Z])(?=.*\d).{8,32}$/.test(np)) return { code: 400, error: '新密码需 8-32 位且含字母和数字' };
    try {
      const u = await auth.getUserByEmail(email);
      if (!u || !u.uid) return { code: 404, error: '用户不存在' };
      await auth.updatePassword(u.uid, np);
      await transporter().sendMail({
        from: process.env.SMTP_USER,
        to: email,
        subject: '[工具铺] 密码已重置',
        text: '你的密码已被站长重置为：' + np + '\n请尽快登录并修改密码。'
      });
      return { code: 0, message: 'ok' };
    } catch (e) { return { code: 500, error: e.message || String(e) }; }
  }

  return { code: 404, error: 'unknown action' };
};
