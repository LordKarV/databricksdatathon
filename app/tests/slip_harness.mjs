// Runs static/slip.js under node: reads {plan, rank, outcome, now} JSON on stdin, prints all renderings.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const ctx = {};
ctx.globalThis = ctx;
vm.runInNewContext(readFileSync(join(here, '..', 'static', 'slip.js'), 'utf8'), ctx);
const S = ctx.RSSlip;
const input = JSON.parse(readFileSync(0, 'utf8'));
const opt = input.plan.options.find(o => o.rank === input.rank);
const backup = input.plan.options.find(o => o.rank !== input.rank) || null;
const m = S.slipModel(input.plan, opt, backup, input.outcome, input.now);
const out = {};
for (const lang of ['en', 'hi']) {
  out[lang] = {html: S.toHtml(m, lang), whatsapp: S.toWhatsApp(m, lang), sms: S.toSms(m, lang)};
}
process.stdout.write(JSON.stringify(out));
