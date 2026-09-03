// 工具铺后端云函数（LeanCloud 云引擎 Node 运行）
// 部署：把本目录（含 package.json）作为云引擎项目部署到 LeanCloud 国内版应用。
// 环境变量（在 LeanCloud 控制台「云引擎 → 设置 → 环境变量」中配置）：
//   LEANCLOUD_APP_ID / LEANCLOUD_APP_KEY / LEANCLOUD_APP_MASTER_KEY  （云引擎自动注入，无需手填）
//   SMTP_USER        你的 163 邮箱地址，如 goutuoshigesha@163.com
//   SMTP_PASS        163 邮箱的 SMTP 授权码（不是登录密码）
//   OWNER_EMAIL      接收找回密码申请的邮箱，默认 goutuoshigesha@163.com
//   ADMIN_PWD        站长后台密码（与前端 index.html 里的 ADMIN_PWD 保持一致）

const AV = require('leancloud-storage');
AV.init({
  appId: process.env.LEANCLOUD_APP_ID,
  appKey: process.env.LEANCLOUD_APP_KEY,
  masterKey: process.env.LEANCLOUD_APP_MASTER_KEY
});

const nodemailer = require('nodemailer');

function transporter() {
  return nodemailer.createTransport({
    host: 'smtp.163.com',
    port: 465,
    secure: true,
    auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS }
  });
}

function ipOf(req) {
  try {
    const m = req.meta || {};
    return m.remoteAddress || m.clientIP || '未知';
  } catch (e) { return '未知'; }
}

// 忘记密码：校验账号存在后，把申请邮件发给站长（绝不发送旧密码，仅通知）
AV.Cloud.define('requestPasswordHelp', async (req) => {
  const id = (req.params.username || '').trim();
  if (!id) throw new Error('请输入账号或手机号');
  AV.Cloud.useMasterKey();
  let u = await new AV.Query('_User').equalTo('username', id).first();
  if (!u) u = await new AV.Query('_User').equalTo('mobilePhoneNumber', id).first();
  if (!u) return { ok: true, sent: false }; // 不暴露账号是否存在，防滥用
  const owner = process.env.OWNER_EMAIL || 'goutuoshigesha@163.com';
  const mobile = u.get('mobilePhoneNumber') || '';
  await transporter().sendMail({
    from: process.env.SMTP_USER,
    to: owner,
    subject: '[工具铺] 用户找回密码申请',
    text:
      '有用户申请找回密码，请登录站长后台为其重置密码并通知用户。\n\n' +
      '账号：' + (u.get('username') || '') + '\n' +
      '手机号：' + mobile + '\n' +
      '注册时间：' + (u.get('createdAt') ? u.get('createdAt').toISOString() : '') + '\n' +
      '申请时间：' + new Date().toLocaleString('zh-CN') + '\n' +
      '来源 IP：' + ipOf(req) + '\n'
  });
  return { ok: true, sent: true };
});

// 站长：列出全部注册用户 + 最近登录时间
AV.Cloud.define('adminListUsers', async (req) => {
  if (req.params.adminPwd !== process.env.ADMIN_PWD) throw new Error('无权限');
  AV.Cloud.useMasterKey();
  const users = await new AV.Query('_User').ascending('createdAt').limit(1000).find();
  const logs = await new AV.Query('LoginLog').descending('createdAt').limit(2000).find();
  const last = {};
  logs.forEach(l => {
    const un = l.get('username');
    if (un && !last[un]) last[un] = l.get('createdAt');
  });
  return users.map(u => ({
    username: u.get('username') || '',
    mobile: u.get('mobilePhoneNumber') || '',
    createdAt: u.get('createdAt') ? u.get('createdAt').toISOString() : '',
    lastLogin: last[u.get('username')] ? last[u.get('username')].toISOString() : ''
  }));
});

// 站长：重置某用户密码（不读取旧密码，仅设定新密码，再告知用户）
AV.Cloud.define('adminResetPassword', async (req) => {
  if (req.params.adminPwd !== process.env.ADMIN_PWD) throw new Error('无权限');
  const username = (req.params.username || '').trim();
  const newPwd = req.params.newPwd || '';
  if (!username || !newPwd) throw new Error('参数缺失');
  if (newPwd.length < 6) throw new Error('新密码至少 6 位');
  AV.Cloud.useMasterKey();
  const u = await new AV.Query('_User').equalTo('username', username).first();
  if (!u) throw new Error('用户不存在');
  u.setPassword(newPwd);
  await u.save();
  return { ok: true };
});

// 记录登录（前端登录成功后调用），用于站长后台"登陆者"审计
AV.Cloud.define('logLogin', async (req) => {
  const username = (req.params.username || '').trim();
  if (!username) return { ok: false };
  AV.Cloud.useMasterKey();
  const Log = AV.Object.extend('LoginLog');
  const o = new Log();
  o.set('username', username);
  o.set('ip', ipOf(req));
  await o.save();
  return { ok: true };
});
