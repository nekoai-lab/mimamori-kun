/* Regenerate the public print assets from their HTML sources.
 * Install playwright-core outside the repository, then run:
 * NODE_PATH=/path/to/node_modules node tools/render_prints.cjs
 * CHROME_PATH optionally selects a Chrome executable.
 */
const { chromium } = require('playwright-core');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
const prints = [
  ['docs/src/今日つくるもの.html', 'docs/今日つくるもの', 2244, 1588, true],
  ['samples/src/sample_elementary.html', 'samples/sample_elementary', 1796, 2246],
  ['samples/src/sample_junior_high.html', 'samples/sample_junior_high', 1796, 2246],
  ['samples/src/sample_elementary_undokai.html', 'samples/sample_elementary_undokai', 1200, 1700],
];

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  try {
    for (const [source, output, width, height, pdf] of prints) {
      const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
      await page.goto(pathToFileURL(path.join(root, source)).href);
      await page.evaluate(() => document.fonts.ready);
      const overflow = await page.evaluate(({ width, height }) =>
        document.documentElement.scrollWidth > width || document.documentElement.scrollHeight > height,
        { width, height });
      if (overflow) throw new Error(`Content exceeds output dimensions: ${source}`);
      await page.screenshot({ path: path.join(root, output + '.png') });
      if (pdf) await page.pdf({ path: path.join(root, output + '.pdf'), preferCSSPageSize: true, printBackground: true });
      await page.close();
      console.log(`Rendered ${output}`);
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
