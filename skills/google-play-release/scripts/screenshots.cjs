'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');

async function actions(page, steps = []) {
  for (const step of steps) {
    const element = page.locator(step.selector);
    if (step.action === 'select') await element.selectOption(step.value);
    else if (step.action === 'click') await element.click();
    else if (step.action === 'fill') await element.fill(step.value);
    else throw Error(`Unsupported screenshot action: ${step.action}`);
  }
}
(async () => {
  const root = path.resolve(process.argv[2]);
  const release = JSON.parse(fs.readFileSync(path.join(root, 'play/release.json')));
  const config = JSON.parse(fs.readFileSync(path.join(root, release.screenshot_config)));
  const output = path.join(root, release.metadata_path, config.locale, 'images/phoneScreenshots');
  const raw = path.join(root, 'build/play-captures/html-preview');
  fs.mkdirSync(raw, {recursive: true});
  const browser = await chromium.launch({headless: true,
    ...(process.env.PLAY_CHROMIUM_EXECUTABLE ? {executablePath: process.env.PLAY_CHROMIUM_EXECUTABLE} : {})});
  const images = [];
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1400}, deviceScaleFactor: 3, reducedMotion: 'reduce'});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => route.request().url().startsWith('file:') || route.request().url().startsWith('data:')
      ? route.continue() : route.abort());
    await page.goto(pathToFileURL(path.join(root, config.page)).href);
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await actions(page, config.actions);
    if (config.css) await page.addStyleTag({content: config.css});
    await page.evaluate(() => document.fonts.ready);
    for (const scene of config.scenes) {
      await actions(page, scene.actions);
      const target = page.locator(config.capture_selector);
      const content = await target.innerText();
      for (const text of scene.expect_text || []) if (!content.includes(text)) throw Error(`${scene.file}: expected text absent: ${text}`);
      if (/undefined|NaN/.test(content)) throw Error(`${scene.file}: invalid rendered content`);
      const source = path.join(raw, scene.file);
      // A scrollable preview editor can clip a target taller than its scroll container.
      // Render the same DOM/CSS in an isolated viewport so every scene includes the full frame.
      const frame = await target.evaluate(element => ({html: element.outerHTML, width: element.offsetWidth,
        height: element.offsetHeight, lang: element.lang || document.documentElement.lang}));
      const styles = await page.locator('style').allTextContents();
      const capture = await browser.newPage({viewport: {width: frame.width, height: frame.height}, deviceScaleFactor: 3,
        reducedMotion: 'reduce'});
      try {
        await capture.setContent(`<html lang="${frame.lang}"><head><style>${styles.join('\n')}\nhtml,body{margin:0!important;padding:0!important;overflow:hidden!important;display:block!important}body>:first-child{margin:0!important;transform:none!important;position:relative!important;left:0!important;top:0!important}</style></head><body>${frame.html}</body></html>`);
        await capture.evaluate(() => document.fonts.ready);
        await capture.screenshot({path: source, animations: 'disabled'});
      } finally { await capture.close(); }
      const converted = path.join(raw, `store-${scene.file}`);
      execFileSync('java', ['-Djava.awt.headless=true', path.resolve(__dirname, '../../../tools/StoreScreenshot.java'), source, converted]);
      images.push({file: scene.file, sha256: crypto.createHash('sha256').update(fs.readFileSync(converted)).digest('hex'),
        width: 1080, height: 1920, logical_width: frame.width, logical_height: frame.height,
        source_kind: config.source_kind, system_ui_example: !!scene.system_ui_example});
    }
    if (errors.length) throw Error(errors.join('; '));
    // Publish only after all scenes rendered successfully. Preserve raw captures for review.
    fs.mkdirSync(output, {recursive: true});
    for (const name of fs.readdirSync(output)) {
      if (/\.(png|jpe?g)$/i.test(name) && !config.scenes.some(s => s.file === name)) fs.unlinkSync(path.join(output, name));
    }
    for (const scene of config.scenes) fs.copyFileSync(path.join(raw, `store-${scene.file}`), path.join(output, scene.file));
    process.stdout.write(JSON.stringify(images));
  } finally { await browser.close(); }
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exit(1); });
