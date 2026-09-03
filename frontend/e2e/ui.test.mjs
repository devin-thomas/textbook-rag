import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import puppeteer, { KnownDevices } from "puppeteer";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appUrl = "http://127.0.0.1:5173/textbooks/";
const artifactDir = process.env.PUPPETEER_ARTIFACT_DIR
  ? path.resolve(process.env.PUPPETEER_ARTIFACT_DIR)
  : path.join(os.tmpdir(), "textbook-rag-puppeteer");
const iphone16ProViewport = KnownDevices["iPhone 16 Pro"].viewport;

const viewports = [
  {
    name: "iphone-16-pro",
    viewport: {
      width: iphone16ProViewport.width,
      height: iphone16ProViewport.height,
      deviceScaleFactor: iphone16ProViewport.deviceScaleFactor,
      isMobile: iphone16ProViewport.isMobile,
      hasTouch: iphone16ProViewport.hasTouch,
    },
  },
  {
    name: "galaxy-s21-ultra",
    viewport: { width: 384, height: 854, deviceScaleFactor: 3.75, isMobile: true, hasTouch: true },
  },
  {
    name: "pc-1280x960",
    viewport: { width: 1280, height: 960, deviceScaleFactor: 1, isMobile: false, hasTouch: false },
  },
  {
    name: "pc-3840x2160",
    viewport: { width: 3840, height: 2160, deviceScaleFactor: 1, isMobile: false, hasTouch: false },
  },
  {
    name: "pc-1920x2160",
    viewport: { width: 1920, height: 2160, deviceScaleFactor: 1, isMobile: false, hasTouch: false },
  },
  {
    name: "m1-macbook-air-more-space",
    viewport: { width: 1680, height: 1050, deviceScaleFactor: 2, isMobile: false, hasTouch: false },
  },
];

const sources = {
  sources: [
    { id: "parallel-operating-systems", title: "Guide to Parallel Operating Systems", course_ids: ["ITSC-1305"] },
    { id: "comptia-tech-plus", title: "CompTIA Tech+ Study Guide", course_ids: ["ITSC-1305"] },
    { id: "missing-link-web", title: "The Missing Link", course_ids: ["ITSE-1311", "ITSE-2302"] },
    { id: "clean-coder", title: "The Clean Coder", course_ids: ["INEW-2330"] },
  ],
};

const historicalConversations = [
  { id: "history-virtual", title: "What is virtual memory?", updated_at: "2026-09-02T15:04:00Z" },
  { id: "history-html", title: "Why use semantic HTML?", updated_at: "2026-09-01T16:15:00Z" },
  { id: "history-commitment", title: "What distinguishes an estimate from a commitment?", updated_at: "2026-08-30T11:03:00Z" },
];

const evidence = [
  {
    id: "chunk-mode-1",
    source_id: "missing-link-web",
    source_title: "The Missing Link",
    physical_page: 64,
    page_label: "64",
    excerpt: "Semantic elements describe meaning and structure, which improves accessibility and maintainability.",
    rank: 1,
    fused_score: 0.82,
  },
  {
    id: "chunk-mode-2",
    source_id: "clean-coder",
    source_title: "The Clean Coder",
    physical_page: 138,
    page_label: "138",
    excerpt: "A commitment is a promise that should be honored, while an estimate expresses probability.",
    rank: 2,
    fused_score: 0.61,
  },
];

const selectedAnswer = {
  status: "ok",
  answer: "Choose each supported principle. [1]",
  actual_provider: "nvidia",
  fallback_used: false,
  retrieval_fallback_used: false,
  select_all_that_apply: true,
  conversation_id: "new-select-all",
  assistant_message_id: "assistant-select-all",
  citations: [{ id: "1", evidence_id: "chunk-mode-1", source_id: "missing-link-web", source_title: "The Missing Link", physical_page: 64, page_label: "64" }],
  evidence,
};

const historyDetail = {
  id: "history-virtual",
  title: "What is virtual memory?",
  messages: [
    { id: "history-user", role: "user", text: "What is virtual memory?", provider_choice: "auto", select_all_that_apply: false },
    {
      id: "history-assistant",
      role: "assistant",
      text: "Virtual memory uses disk storage as an extension of physical memory.",
      provider_choice: "auto",
      actual_provider: "nvidia",
      fallback_used: false,
      retrieval_fallback_used: false,
      select_all_that_apply: false,
      status: "ok",
      citations: [{ id: "1", evidence_id: "chunk-mode-1" }],
      evidence: [evidence[0]],
    },
  ],
};

function jsonResponse(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

async function installApiMocks(page) {
  let lastQueryBody;
  let queryCount = 0;
  await page.setRequestInterception(true);
  page.on("request", async (request) => {
    if (request.isInterceptResolutionHandled()) return;
    const requestUrl = new URL(request.url());
    if (!requestUrl.pathname.startsWith("/textbooks/api/")) {
      await request.continue();
      return;
    }

    const pathName = requestUrl.pathname;
    if (pathName === "/textbooks/api/health") {
      await request.respond(jsonResponse({ status: "ok", ollama: { configured: true } }));
      return;
    }
    if (pathName === "/textbooks/api/sources") {
      await request.respond(jsonResponse(sources));
      return;
    }
    if (pathName === "/textbooks/api/conversations" && request.method() === "GET") {
      const conversations = queryCount > 0
        ? [{ id: "new-select-all", title: "Which principles apply?", updated_at: "2026-09-03T12:00:00Z" }, ...historicalConversations]
        : historicalConversations;
      await request.respond(jsonResponse({ conversations }));
      return;
    }
    if (pathName === "/textbooks/api/query" && request.method() === "POST") {
      queryCount += 1;
      lastQueryBody = JSON.parse(request.postData() ?? "{}");
      await request.respond(jsonResponse(selectedAnswer));
      return;
    }
    if (pathName === "/textbooks/api/conversations/history-virtual") {
      await request.respond(jsonResponse(historyDetail));
      return;
    }
    if (/^\/textbooks\/api\/sources\/[^/]+\/pdf$/.test(pathName)) {
      await request.respond({ status: 200, contentType: "application/pdf", body: "%PDF-1.4\n% textbook test fixture\n" });
      return;
    }
    await request.continue();
  });
  return {
    get lastQueryBody() {
      return lastQueryBody;
    },
  };
}

function startVite() {
  const viteBin = path.join(frontendRoot, "node_modules", "vite", "bin", "vite.js");
  const server = spawn(process.execPath, [viteBin, "--host", "127.0.0.1", "--port", "5173"], {
    cwd: frontendRoot,
    env: { ...process.env, BROWSER: "none" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  server.stdout.on("data", (chunk) => { output += chunk.toString(); });
  server.stderr.on("data", (chunk) => { output += chunk.toString(); });
  server.__output = () => output;
  return server;
}

async function waitForVite(server) {
  const deadline = Date.now() + 20000;
  let lastError = "";
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`Vite exited with code ${server.exitCode}.\n${server.__output()}`);
    }
    try {
      const response = await fetch(appUrl);
      if (response.ok) return;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await delay(200);
  }
  throw new Error(`Vite did not become ready: ${lastError}\n${server.__output()}`);
}

async function assertPageHealth(page, viewportName) {
  assert.equal(await page.title(), "Textbook Desk", `${viewportName}: page title`);
  assert.equal(await page.url(), appUrl, `${viewportName}: page URL`);
  const bodyText = await page.$eval("body", (element) => element.innerText);
  assert.match(bodyText, /Textbook Desk/);
  assert.doesNotMatch(bodyText, /Internal Server Error|Vite Error|Failed to compile/i);

  const layout = await page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    const bodyStyle = getComputedStyle(body);
    const target = document.querySelector(".mode-toggle");
    const targetRect = target?.getBoundingClientRect();
    const interactive = [...document.querySelectorAll("button, select, textarea, a")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden";
      })
      .map((element) => ({ tag: element.tagName, label: element.getAttribute("aria-label") ?? element.textContent?.trim(), width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }));
    return {
      scrollWidth: Math.max(root.scrollWidth, body.scrollWidth),
      viewportWidth: window.innerWidth,
      fontFamily: bodyStyle.fontFamily,
      modeTarget: targetRect ? { width: targetRect.width, height: targetRect.height } : null,
      interactive,
    };
  });
  assert.ok(layout.scrollWidth <= layout.viewportWidth + 1, `${viewportName}: horizontal overflow ${layout.scrollWidth} > ${layout.viewportWidth}`);
  assert.match(layout.fontFamily, /IBM Plex Sans|Segoe UI|Arial/i, `${viewportName}: sans-serif body font`);
  assert.doesNotMatch(layout.fontFamily, /Newsreader|Georgia|Times New Roman/i, `${viewportName}: serif body font`);
  assert.ok(layout.modeTarget && layout.modeTarget.height >= 44, `${viewportName}: checkbox row is a 44px touch target`);
  const undersized = layout.interactive.filter((item) => item.height < 44 && item.tag !== "A");
  assert.deepEqual(undersized, [], `${viewportName}: undersized interactive controls`);
  assert.ok(await page.$('input[aria-label="Select all that apply"]'), `${viewportName}: select-all checkbox exists`);
}

async function loadApp(page, viewportName, viewport) {
  await page.setViewport(viewport);
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('textarea[placeholder="Ask your textbooks…"]');
  await page.waitForSelector('input[aria-label="Select all that apply"]');
  await page.waitForFunction(() => document.querySelectorAll(".history-select").length >= 3);
  await page.evaluate(() => document.fonts?.ready);
  await assertPageHealth(page, viewportName);
}

async function assertHistoryList(page, viewportName) {
  const titles = await page.$$eval(".history-select span", (items) => items.map((item) => item.textContent?.trim()));
  assert.deepEqual(titles, historicalConversations.map((item) => item.title), `${viewportName}: historical question list is preserved`);
}

async function runHistoryFlow(page, viewportName, isMobile) {
  await assertHistoryList(page, viewportName);
  if (isMobile) {
    await page.click('button[aria-label="Open history"]');
    await page.waitForSelector(".history-rail.mobile-open");
    assert.ok(await page.$eval(".history-rail.mobile-open", (element) => getComputedStyle(element).transform !== "none"));
  } else {
    const search = page.locator('input[aria-label="Find a question"]');
    await search.fill("semantic");
    assert.equal(await page.$$eval(".history-select", (items) => items.length), 1, `${viewportName}: history search filters results`);
    await search.click();
    await page.keyboard.down("Control");
    await page.keyboard.press("A");
    await page.keyboard.up("Control");
    await page.keyboard.press("Backspace");
    await page.waitForFunction(() => document.querySelector('input[aria-label="Find a question"]')?.value === "");
    await page.waitForFunction(() => document.querySelectorAll(".history-select").length === 3);
  }
  const historyButton = await page.$('button.history-select');
  assert.ok(historyButton, `${viewportName}: historical question button exists`);
  await historyButton.evaluate((element) => element.scrollIntoView({ block: "center", inline: "nearest" }));
  await historyButton.click();
  await page.waitForFunction(() => document.querySelector(".answer-article h1")?.textContent?.includes("What is virtual memory?") === true);
  assert.equal(await page.$eval(".history-select[aria-current='page'] span", (element) => element.textContent?.trim()), "What is virtual memory?");
  if (isMobile) assert.equal(await page.$(".history-rail.mobile-open"), null, `${viewportName}: history drawer closes after selection`);
}

async function runScopeFlow(page, viewportName) {
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector('button.scope-button');
  await page.click('button.scope-button');
  await page.waitForSelector('[role="dialog"][aria-label="Choose textbook scope"]');
  const scopeCount = await page.$$eval('[role="dialog"] input[type="checkbox"]', (items) => items.length);
  assert.ok(scopeCount >= 4, `${viewportName}: scope lists the four configured textbooks`);
  await page.click('button[aria-label="Close filters"]');
  assert.equal(await page.$('[role="dialog"][aria-label="Choose textbook scope"]'), null, `${viewportName}: scope dialog closes`);
}

async function runSelectAllFlow(page, viewportName, mockState) {
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[aria-label="Select all that apply"]');
  const checkbox = 'input[aria-label="Select all that apply"]';
  assert.equal(await page.$eval(checkbox, (element) => element.checked), false, `${viewportName}: select-all starts unchecked`);
  await page.click(checkbox);
  assert.equal(await page.$eval(checkbox, (element) => element.checked), true, `${viewportName}: select-all toggles on`);
  await page.type('textarea[placeholder="Ask your textbooks…"]', "Which principles apply?");
  await page.click('button[aria-label="Ask question"]');
  await page.waitForSelector(".answer-mode-note");
  assert.match(await page.$eval(".answer-mode-note", (element) => element.textContent ?? ""), /Multiple correct answers/);
  assert.equal(mockState.lastQueryBody?.select_all_that_apply, true, `${viewportName}: API receives select-all mode`);
  assert.equal(await page.$eval('input[aria-label="Select all that apply"]', (element) => element.checked), true, `${viewportName}: mode remains visible after answer`);
  await page.waitForSelector(".evidence-panel");
  const postAnswerLayout = await page.evaluate(() => ({
    scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    viewportWidth: window.innerWidth,
    evidenceVisible: Boolean(document.querySelector(".evidence-panel")),
    evidenceExpanded: Boolean(document.querySelector(".evidence-panel.mobile-expanded")),
  }));
  assert.ok(postAnswerLayout.scrollWidth <= postAnswerLayout.viewportWidth + 1, `${viewportName}: no overflow after evidence opens`);
  assert.equal(postAnswerLayout.evidenceVisible, true, `${viewportName}: evidence opens after answered query`);
  if (windowIsMobile(page)) {
    assert.equal(postAnswerLayout.evidenceExpanded, false, `${viewportName}: mobile evidence sheet starts collapsed`);
    await page.click('button[aria-label="Expand evidence"]');
    await page.waitForSelector('.evidence-panel.mobile-expanded');
    assert.equal(await page.$('.evidence-panel.mobile-expanded') !== null, true, `${viewportName}: mobile evidence sheet expands`);
  }
}

function windowIsMobile(page) {
  return page.viewport().isMobile === true;
}

async function main() {
  await mkdir(artifactDir, { recursive: true });
  const server = startVite();
  let browser;
  try {
    await waitForVite(server);
    browser = await puppeteer.launch({ headless: true, userDataDir: path.join(artifactDir, "browser-profile") });
    for (const { name, viewport } of viewports) {
      const page = await browser.newPage();
      const consoleErrors = [];
      const httpErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });
      page.on("pageerror", (error) => consoleErrors.push(error.message));
      page.on("response", (response) => {
        if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`);
      });
      const mockState = await installApiMocks(page);
      try {
        await loadApp(page, name, viewport);
        await assertHistoryList(page, name);
        await page.screenshot({ path: path.join(artifactDir, `${name}-initial.png`), fullPage: false });
        await runHistoryFlow(page, name, viewport.isMobile === true);
        await runScopeFlow(page, name);
        await runSelectAllFlow(page, name, mockState);
        await page.screenshot({ path: path.join(artifactDir, `${name}-select-all.png`), fullPage: false });
        assert.deepEqual(httpErrors, [], `${name}: HTTP health`);
        assert.deepEqual(consoleErrors, [], `${name}: console health`);
        process.stdout.write(`PASS ${name}\n`);
      } finally {
        await page.close();
      }
    }
    process.stdout.write(`Puppeteer artifacts: ${artifactDir}\n`);
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null) server.kill();
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
});
