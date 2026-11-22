// Runs app/static/pack.js under node against built packs and prints the query result as JSON.
// Usage: node app/packs/check_loader.mjs <pack.json.gz>[,<pack.json.gz>...] <lat> <lon> <service>
// One pack runs RSPack.query; several (comma-separated) run RSPack.queryAll, the offline answer over saved packs.
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

const [packPath, lat, lon, service] = process.argv.slice(2);
const src = readFileSync(fileURLToPath(new URL('../static/pack.js', import.meta.url)), 'utf8');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src, ctx);
const packs = packPath.split(',').map(p => JSON.parse(gunzipSync(readFileSync(p)).toString('utf8')));
process.stdout.write(JSON.stringify(packs.length > 1 ? ctx.RSPack.queryAll(packs, +lat, +lon, service)
  : ctx.RSPack.query(packs[0], +lat, +lon, service)));
