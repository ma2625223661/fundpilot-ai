// Renders the app icons for "add to home screen" from public/favicon.svg.
// Run once after changing the SVG: `node scripts/make-icons.mjs`. The PNGs are
// committed, so normal builds do not need this script or its dependency.
import { readFileSync, writeFileSync } from 'node:fs';
import { Resvg } from '@resvg/resvg-js';

const svg = readFileSync(new URL('../public/favicon.svg', import.meta.url));
for (const size of [180, 192, 512]) {
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: size } }).render().asPng();
  const name = size === 180 ? 'apple-touch-icon.png' : `icon-${size}.png`;
  writeFileSync(new URL(`../public/${name}`, import.meta.url), png);
  console.log(`public/${name}`, png.length, 'bytes');
}
