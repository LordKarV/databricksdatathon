// Runs app.js's own engHi (the Hindi engine table lookup behind E()) under node, so the test checks the page's code,
// not a copy. Reads {items: [{text, q}]} JSON on stdin; prints [hindi or null] in the same order.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'static', 'app.js'), 'utf8');
const start = app.indexOf('const reEsc'), end = app.indexOf('function E(');
if (start < 0 || end < start) throw new Error('engHi not found in app.js');
const ctx = {I18N: {hi: JSON.parse(readFileSync(join(here, '..', 'static', 'i18n', 'hi.json'), 'utf8'))}};
vm.runInNewContext(app.slice(start, end) + '\nglobalThis.engHi = engHi;', ctx);
const {items} = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(items.map(({text, q}) => ctx.engHi(String(text), q))));
