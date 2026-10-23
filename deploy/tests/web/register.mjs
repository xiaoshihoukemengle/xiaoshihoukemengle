// 网页注册流程测试：用真浏览器走一遍 邮箱 + 用户名 + 密码 注册 → 收验证码 → 完成，
// 再用邮箱登录。验证码从开发环境的 mailpit 收信箱读取（docker compose --profile dev）。
//
//   DOMAIN=chat.test RESOLVE=127.0.0.1 node register.mjs
//
// CHROMIUM_PATH 指定浏览器；不填则用 playwright 自带的（npx playwright install chromium）。

import { chromium } from "playwright-core";
import { randomBytes } from "node:crypto";

const domain = process.env.DOMAIN;
const resolve = process.env.RESOLVE;
const mailpit = process.env.MAILPIT_URL ?? "http://127.0.0.1:8025";
if (!domain) throw new Error("需要 DOMAIN");

const id = randomBytes(3).toString("hex");
const username = `web${id}`;
const email = `${username}@example.org`;
const password = `Web-${randomBytes(9).toString("base64url")}`;

const args = resolve
  ? [`--host-resolver-rules=MAP ${domain} ${resolve}, MAP *.${domain} ${resolve}`, "--no-proxy-server"]
  : [];
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, args });
const context = await browser.newContext({ ignoreHTTPSErrors: Boolean(resolve), locale: "zh-CN" });
const page = await context.newPage();

let failed = 0;
async function step(name, fn) {
  try {
    await fn();
    console.log(`  ok   ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`  FAIL ${name}: ${err.message.split("\n")[0]}`);
    await page.screenshot({ path: `fail-${id}-${failed}.png`, fullPage: true }).catch(() => {});
  }
}

async function latestCode(to) {
  for (let i = 0; i < 30; i += 1) {
    const list = await fetch(`${mailpit}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`).then((r) => r.json());
    const msg = list.messages?.[0];
    if (msg) {
      const full = await fetch(`${mailpit}/api/v1/message/${msg.ID}`).then((r) => r.json());
      const code = full.Text.match(/\b(\d{6})\b/);
      if (code) return code[1];
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`没收到发给 ${to} 的验证码邮件`);
}

console.log(`网页注册测试，账号 ${username}`);

await step("打开注册页，填写用户名、邮箱、密码", async () => {
  await page.goto(`https://auth.${domain}/register`);
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', password);
  await page.fill('input[name="password_confirm"]', password);
  await Promise.all([page.waitForURL((u) => !u.pathname.endsWith("/register/password")), page.click('button[type="submit"]')]);
});

await step("收到邮箱验证码并通过验证", async () => {
  const code = await latestCode(email);
  await page.fill('input[name="code"]', code);
  await Promise.all([page.waitForNavigation(), page.click('button[type="submit"]')]);
});

await step("设置昵称，完成注册", async () => {
  if (await page.locator('input[name="display_name"]').count()) {
    await page.fill('input[name="display_name"]', `网页用户 ${id}`);
    await Promise.all([page.waitForNavigation(), page.click('button[type="submit"]')]);
  }
  // 注册完成后回到首页，显示“登录为 用户名”
  await page.waitForURL(`https://auth.${domain}/`, { timeout: 15000 });
  await page.getByText(username, { exact: true }).waitFor({ timeout: 5000 });
});

await step("新浏览器里用邮箱 + 密码登录", async () => {
  const fresh = await browser.newContext({ ignoreHTTPSErrors: Boolean(resolve) });
  const p = await fresh.newPage();
  await p.goto(`https://auth.${domain}/login`);
  await p.fill('input[name="username"]', email);
  await p.fill('input[name="password"]', password);
  await Promise.all([p.waitForURL(`https://auth.${domain}/`, { timeout: 15000 }), p.click('button[type="submit"]')]);
  await p.getByText(username, { exact: true }).waitFor({ timeout: 5000 });
  await fresh.close();
});

await step("注册的账号能用用户名登录聊天接口", async () => {
  const result = await page.evaluate(
    async ({ hs, user, pass }) => {
      const r = await fetch(`${hs}/_matrix/client/v3/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "m.login.password", identifier: { type: "m.id.user", user }, password: pass }),
      });
      return { status: r.status, body: await r.json() };
    },
    { hs: `https://matrix.${domain}`, user: username, pass: password },
  );
  if (result.status !== 200 || result.body.user_id !== `@${username}:${domain}`) {
    throw new Error(`HTTP ${result.status} ${JSON.stringify(result.body)}`);
  }
});

await browser.close();
console.log(failed ? `\n失败 ${failed} 项` : "\n全部通过");
process.exit(failed ? 1 : 0);
