// Runs app/static/pack.js under node against a built pack and prints the query result as JSON.
// Usage: node app/packs/check_loader.mjs <pack.json.gz> <lat> <lon> <service>
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

const [packPath, lat, lon, service] = process.argv.slice(2);
const src = readFileSync(fileURLToPath(new URL('../static/pack.js', import.meta.url)), 'utf8');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src, ctx);
const pack = JSON.parse(gunzipSync(readFileSync(packPath)).toString('utf8'));
process.stdout.write(JSON.stringify(ctx.RSPack.query(pack, +lat, +lon, service)));
