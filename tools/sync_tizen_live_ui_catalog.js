/* Build-time sync of visible Live rows only: never exports source URLs or resolver metadata. */
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const source = process.argv[2];
if (!source) throw new Error('Usage: node tools/sync_tizen_live_ui_catalog.js <Kodi addon_data directory>');

const catalogPath = path.join(root, 'tizen', 'PrippiStreamTV', 'data', 'live_channels.json');
const catalog = JSON.parse(fs.readFileSync(catalogPath, 'utf8'));
const rows = [
  ['iptv_calcio', 'calcio'],
  ['iptv_cinema', 'cinema'],
  ['iptv_dazn', 'dazn'],
  ['iptv_documentari', 'documentari'],
  ['iptv_intrattenimento', 'intrattenimento']
];
const key = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
const known = new Set(catalog.map((item) => `${item.live_row}:${key(item.title)}`));
let added = 0;

for (const [cacheName, liveRow] of rows) {
  const file = path.join(source, `sportchannels_${cacheName}.json`);
  if (!fs.existsSync(file)) continue;
  const payload = JSON.parse(fs.readFileSync(file, 'utf8'));
  for (const entry of payload.data || []) {
    const title = String(entry.title || '').trim();
    const identity = `${liveRow}:${key(title)}`;
    if (!title || known.has(identity)) continue;
    known.add(identity);
    catalog.push({
      channel: 'catalog', title, fulltitle: title, contentType: 'video', action: 'catalog_only',
      url: '', video_url: '', callSign: '', id: '',
      plot: 'Canale presente nel catalogo Live. La riproduzione richiede una sorgente autorizzata.',
      logo: '', thumbnail: '', is_live_channel: true, isLive: true,
      live_row: liveRow, catalog_only: true
    });
    added += 1;
  }
}

fs.writeFileSync(catalogPath, JSON.stringify(catalog, null, 2) + '\n', 'utf8');
console.log(`Tizen Live UI: ${added} canali aggiunti; totale ${catalog.length}`);
