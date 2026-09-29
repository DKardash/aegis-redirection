const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.join(__dirname, '../web/static');
const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const text = ['TELEGRAM_DNS', 'DISCORD_DNS', 'PUBG_DNS'].map((name, i) => `# ==================== ${i+1}. ${name} ====================\n/ip firewall address-list\nadd list=${name} address=example.com disabled=no`).join('\n');
const box = { querySelectorAll: () => [] };
const context = {
  $: () => box, escapeHtml: s => s, alResolvedText: '', alResolvedGroups: null,
  fetch: async () => ({ ok: true, text: async () => text }),
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function alParseGroups('), source.indexOf('async function resolveAddressLists(')), context);
const groups = context.alParseGroups(text);
assert.deepEqual(JSON.parse(JSON.stringify(groups.map(g => [g.title, g.count]))),
  [['TELEGRAM_DNS', 1], ['DISCORD_DNS', 1], ['PUBG_DNS', 1]]);
context.loadAddressLists().then(() => {
  for (const name of ['TELEGRAM_DNS', 'DISCORD_DNS', 'PUBG_DNS']) assert.ok(box.innerHTML.includes(name));
  assert.equal((box.innerHTML.match(/class="al-group"/g) || []).length, 3);
  console.log('PASS: three lists parsed and rendered');
}).catch(error => { console.error(error); process.exitCode = 1; });
