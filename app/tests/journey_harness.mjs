// Runs static/slip.js + static/journey.js under node: reads {plans: {name: plan}, now} JSON on stdin and prints
// every card in both languages, plus the two shareJourney paths (Web Share with files, download) on fakes.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const input = JSON.parse(readFileSync(0, 'utf8'));

function load(extra) {
  const ctx = {File, URL, setTimeout, ...extra};
  ctx.globalThis = ctx;
  for (const f of ['slip.js', 'journey.js']) vm.runInNewContext(readFileSync(join(here, '..', 'static', f), 'utf8'), ctx);
  return ctx.RSJourney;
}

const J = load({});
const out = {cards: {}, share: {}};
for (const [name, plan] of Object.entries(input.plans)) {
  out.cards[name] = {};
  for (const lang of ['en', 'hi']) out.cards[name][lang] = J.buildJourney(plan, lang, {now: input.now});
}

const plan = Object.values(input.plans)[0];
let shared = null;
const viaShare = load({navigator: {canShare: d => d.files.length === 1, share: async d => { shared = d; }}});
out.share.shareResult = await viaShare.shareJourney(plan, 'hi', {now: input.now});
out.share.shared = shared && {title: shared.title, name: shared.files[0].name, type: shared.files[0].type,
  size: shared.files[0].size};

let clicked = null;
const doc = {body: {appendChild() {}}, createElement: () => ({click() { clicked = {name: this.download}; }, remove() {}})};
const viaDownload = load({navigator: {canShare: () => false}, document: doc});
out.share.downloadResult = await viaDownload.shareJourney(plan, 'en', {now: input.now});
out.share.downloaded = clicked;
process.stdout.write(JSON.stringify(out));
