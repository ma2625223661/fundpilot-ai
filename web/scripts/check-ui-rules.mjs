// Enforces the hard UI rules from ../AGENTS.md on everything under src/.
// Exit code 1 on any violation, so it can gate commits and CI:  npm run check:ui
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = path.join(web, 'src');
// Generated verbatim copies of the old logic are exempt. shadcn's own component
// sources may use arbitrary values and native elements internally, but the rules
// marked `everywhere` (the visual red lines) apply to them too.
const EXEMPT = [path.join(src, 'lib', 'legacy')];
const UI_DIR = path.join(src, 'components', 'ui');
const THEME_FILE = path.join(src, 'index.css');

const RULES = [
  { id: 'gradient', test: /gradient/i, message: '禁止渐变色', everywhere: true },
  { id: 'gradient-stop', test: /\b(?:from|via|to)-(?:[a-z]+-\d{2,3}|primary|accent|background|card|muted)\b/, message: '禁止渐变色（渐变色标）' },
  { id: 'emoji', test: /[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}]/u, message: '禁止 emoji，图标请用 lucide-react', everywhere: true },
  { id: 'symbol-icon', test: /[←-⇿☀-➿■-◿⬀-⯿]/u, message: '禁止用 Unicode 符号充当图标，图标请用 lucide-react', everywhere: true },
  { id: 'backdrop-blur', test: /\bbackdrop-blur/, message: '禁止 backdrop-blur 装饰', everywhere: true },
  { id: 'big-shadow', test: /\bshadow-(?:md|lg|xl|2xl|inner)\b|\bshadow-\[/, message: '阴影只用 shadow-xs / shadow-sm', everywhere: true },
  { id: 'glow', test: /\bdrop-shadow|\bshadow-(?:primary|rise|fall|warning|destructive|chart)/, message: '禁止发光与彩色阴影', everywhere: true },
  { id: 'tracking', test: /\btracking-/, message: '禁止修改字间距', everywhere: true },
  { id: 'fixed-black-white', test: /\b(?:bg|text|border|ring)-(?:black|white)\b/, message: '禁止写死黑白，使用主题令牌', everywhere: true },
  { id: 'hex-color', test: /#[0-9a-fA-F]{3,8}\b/, message: '禁止写死颜色，使用主题令牌', skip: f => f === THEME_FILE },
  { id: 'rgb-color', test: /\b(?:rgb|rgba|hsl|hsla|oklch)\(/, message: '禁止写死颜色，使用主题令牌', skip: f => f === THEME_FILE },
  { id: 'palette-color', test: /\b(?:bg|text|border|ring|fill|stroke)-(?:red|green|blue|purple|violet|pink|indigo|yellow|orange|emerald|teal|cyan|sky|lime|amber|rose|fuchsia|slate|gray|zinc|neutral|stone)-\d{2,3}\b/, message: '禁止直接使用 Tailwind 色板，使用语义色（如 text-rise）' },
  { id: 'arbitrary-value', test: /\b[a-z][a-z-]*-\[[^\]]+\]/, message: '禁止任意值 [...]，使用默认刻度' },
  { id: 'h-screen', test: /\bh-screen\b/, message: '使用 h-dvh / min-h-dvh 代替 h-screen' },
  { id: 'native-control', test: /<(?:button|input|select|textarea|dialog)\b/, message: '禁止原生交互控件，使用 components/ui 中的组件', only: f => f.endsWith('.tsx') },
  { id: 'inner-html', test: /dangerouslySetInnerHTML/, message: '禁止 dangerouslySetInnerHTML' },
];

function* files(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (EXEMPT.some(e => full === e || full.startsWith(e + path.sep))) continue;
    if (entry.isDirectory()) yield* files(full);
    else if (/\.(tsx?|css)$/.test(entry.name)) yield full;
  }
}

const problems = [];
for (const file of files(src)) {
  // Block comments may describe the rules themselves; blank them but keep line numbers.
  const text = fs.readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '));
  const lines = text.split(/\r?\n/);
  lines.forEach((line, i) => {
    const code = line.replace(/\/\/.*$/, '');
    for (const rule of RULES) {
      if (rule.skip?.(file) || (rule.only && !rule.only(file))) continue;
      if (file.startsWith(UI_DIR + path.sep) && !rule.everywhere) continue;
      if (rule.test.test(code)) problems.push(`${path.relative(web, file)}:${i + 1}  ${rule.message}  [${rule.id}]\n    ${line.trim()}`);
    }
  });
}

if (problems.length) {
  console.error(problems.join('\n'));
  console.error(`\n${problems.length} 处违反 UI 规范`);
  process.exit(1);
}
console.log('UI 规范检查通过');
