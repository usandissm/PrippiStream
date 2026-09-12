# -*- coding: utf-8 -*-
"""Private IPTV catalog loader and local lease allocator for Kodi 2.x.

The catalog is loaded only from addon data (never bundled in the public ZIP).
The allocator is a local fallback; a shared broker can implement the same API.
"""
import hashlib, json, os, random, re, threading, time
try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
except ImportError:
    from urllib2 import Request, urlopen
    from urllib import urlencode
from platformcode import config, logger

_TTL = 6 * 3600
_lock = threading.Lock()
_catalog, _loaded_at = None, 0
_leases = {}
_logo_index = None
_accounts, _accounts_loaded_at = None, 0
_account_streams = {}
_pool_attempts = {}
_warm_account_ids = set()
_warmup_done_at = 0
_ACCOUNT_TTL = 30 * 60
_STREAM_MAP_TTL = 6 * 3600

def _runtime_seed_paths(filename):
    """Candidate paths for immutable packaged data.

    Kodi's runtime is the addon folder; Android's Python code itself lives in
    Chaquopy's AssetFinder while data assets are copied to ``files/pydata``.
    ``prippi_env.RUNTIME_DIR`` is therefore authoritative on Android.
    """
    roots = []
    try:
        import prippi_env
        if getattr(prippi_env, 'RUNTIME_DIR', ''):
            roots.append(prippi_env.RUNTIME_DIR)
    except Exception:
        pass
    try:
        roots.append(config.get_runtime_path())
    except Exception:
        pass
    return [os.path.join(root, filename) for root in roots if root]


def _android_runtime_path(filename):
    """Return the copied Android payload, never Chaquopy's AssetFinder path.

    The Android engine modules are imported from AssetFinder, while JSON and
    artwork live in ``files/pydata``.  Keep this distinction here so a cold
    Home can always expose the complete IPTV catalog without a network probe.
    """
    try:
        import prippi_env
        root = getattr(prippi_env, 'RUNTIME_DIR', '')
        if root and os.path.basename(os.path.normpath(root)) == 'pydata':
            candidate = os.path.join(root, filename)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return None


def _path():
    try:
        # Android's current, atomically-installed payload is authoritative.
        # Do this before addon data: the latter is the app's writable files
        # root and can contain stale remnants after an APK update.
        runtime_path = _android_runtime_path('iptv_catalog.json')
        if runtime_path:
            return runtime_path
        data_path = os.path.join(config.get_data_path(), 'iptv_catalog.json')
        if os.path.isfile(data_path):
            return data_path
        return next((candidate for candidate in _runtime_seed_paths('iptv_catalog.json')
                     if os.path.isfile(candidate)), None)
    except Exception: return None

def _accounts_path():
    try: return os.path.join(config.get_data_path(), 'iptv_accounts.json')
    except Exception: return None

def _load_accounts():
    global _accounts, _accounts_loaded_at
    now = time.time()
    if _accounts is not None and now - _accounts_loaded_at < _ACCOUNT_TTL:
        return _accounts
    # Same rule as the catalog: on Android the pydata snapshot is the only
    # trusted account seed.  In Kodi, retain addon-data precedence.
    android_seed = _android_runtime_path('iptv_accounts.json')
    path = android_seed or _accounts_path()
    # Il pool aggiornato in addon_data ha precedenza. Nelle nuove installazioni
    # usa il seed incluso nella release: così Prippi funziona anche se sul box
    # non è installato TheGroove e i dispositivi non devono comunicare fra loro.
    # Kodi keeps the private seed under resources/data. Android copies its
    # runtime payload into ``pydata`` and keeps the same seed at its root, so
    # accept both layouts without ever exposing it through the public catalog.
    seed_paths = _runtime_seed_paths('iptv_accounts.json')
    try:
        seed_paths.append(os.path.join(
            config.get_runtime_path(), 'resources', 'data', 'iptv_accounts.json'))
    except Exception:
        pass
    try:
        source = path if path and os.path.isfile(path) else next(
            (candidate for candidate in seed_paths if os.path.isfile(candidate)),
            '',
        )
        blob = json.load(open(source, 'r', encoding='utf-8')) if os.path.isfile(source) else {}
        rows = blob.get('accounts', []) if isinstance(blob, dict) else []
        _accounts = [x for x in rows if x.get('host') and x.get('username') and x.get('password')]
    except Exception as exc:
        logger.error('[IPTV] account pool load: %s' % exc)
        _accounts = []
    _accounts_loaded_at = now
    return _accounts

def _load():
    global _catalog, _loaded_at
    with _lock:
        if _catalog is not None and time.time() - _loaded_at < _TTL: return _catalog
        p = _path()
        try:
            blob = json.load(open(p, 'r', encoding='utf-8')) if p and os.path.isfile(p) else {}
            _catalog = blob.get('items', []) if isinstance(blob, dict) else []
        except Exception as exc:
            logger.error('[IPTV] catalog load: %s' % exc); _catalog = []
        _loaded_at = time.time(); return _catalog

def invalidate():
    global _loaded_at
    with _lock: _loaded_at = 0

def channels(category=None):
    rows = list(_load())
    return [x for x in rows if not category or x.get('category') == category]

def _account_api(account, action='', timeout=4):
    scheme = account.get('scheme') or 'http'
    base = '%s://%s/player_api.php' % (scheme, account['host'])
    query = {'username': account['username'], 'password': account['password']}
    if action:
        query['action'] = action
    req = Request(base + '?' + urlencode(query),
                  headers={'User-Agent': 'PrippiStream/2.x', 'Accept': 'application/json'})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8', 'replace'))

def _account_free(account):
    try:
        data = _account_api(account, timeout=3)
        info = data.get('user_info', {}) if isinstance(data, dict) else {}
        active = int(info.get('active_cons') or 0)
        maximum = int(info.get('max_connections') or 0)
        enabled = str(info.get('auth', '1')) == '1' and str(info.get('status', 'Active')).lower() == 'active'
        if not enabled or maximum <= 0 or active >= maximum:
            return None
        return active, maximum
    except Exception as exc:
        logger.debug('[IPTV] panel unavailable %s: %s' % (account.get('host'), exc))
        return None

def _norm_title(value):
    value = re.sub(r'\[[^]]+\]', ' ', str(value or '').lower())
    value = re.sub(r'\b(?:flh|fhd|full\s*hd|hd|sd|buffering)\b', ' ', value)
    value = value.replace('&', ' and ')
    return re.sub(r'[^a-z0-9+]+', ' ', value).strip()

def _account_channel(account, title):
    """Return the live stream id matching *title* on one free account."""
    aid = '%s://%s/%s' % (account.get('scheme') or 'http', account['host'], account['username'])
    now = time.time()
    cached = _account_streams.get(aid)
    if cached and now - cached[0] < _STREAM_MAP_TTL:
        stream_map = cached[1]
    else:
        try:
            rows = _account_api(account, action='get_live_streams', timeout=8)
            stream_map = {}
            for row in rows if isinstance(rows, list) else []:
                name = _norm_title(row.get('name'))
                sid = row.get('stream_id')
                if name and sid is not None:
                    # FHD/full-HD wins when a provider exposes duplicates.
                    quality = 2 if re.search(r'\b(?:fhd|full\s*hd)\b', str(row.get('name', '')).lower()) else 1
                    previous = stream_map.get(name)
                    if previous is None or quality > previous[1]:
                        stream_map[name] = (str(sid), quality)
            _account_streams[aid] = (now, stream_map)
        except Exception as exc:
            logger.debug('[IPTV] lineup unavailable %s: %s' % (account.get('host'), exc))
            return None
    needle = _norm_title(title)
    exact = stream_map.get(needle)
    if exact:
        return exact[0]
    # Tolerate provider prefixes/suffixes without matching a different channel.
    candidates = [(name, data) for name, data in stream_map.items()
                  if name.endswith(' ' + needle) or needle.endswith(' ' + name)]
    if candidates:
        candidates.sort(key=lambda pair: (-pair[1][1], abs(len(pair[0]) - len(needle))))
        return candidates[0][1][0]
    return None

def _pool_url(title, lease_id, excluded=None):
    """Select a remotely free Group-E account and resolve the channel on it.

    Clients never communicate with each other: every installation reads the
    provider panel's active_cons/max_connections state. Randomised ordering
    spreads simultaneous clients across the large account pool; playback retry
    supplies a different *lease_id* and therefore a different starting point.
    """
    accounts = list(_load_accounts())
    if not accounts:
        return None
    excluded = set(excluded or [])
    seed = hashlib.sha256(('%s|%s|%d' % (title, lease_id, time.time() // 20)).encode('utf-8')).digest()
    rnd = random.Random(seed)
    rnd.shuffle(accounts)
    # Gli account già preparati dopo il primo paint hanno l'intero palinsesto
    # in RAM: provarli prima elimina la richiesta get_live_streams dal percorso
    # del clic, mantenendo comunque casuale l'ordine fra quelli pronti.
    accounts.sort(key=lambda account: 0 if ('%s://%s/%s' % (
        account.get('scheme') or 'http', account['host'],
        account['username'])) in _warm_account_ids else 1)
    # Probe small batches concurrently: with 100+ lists this usually finds a
    # free slot in ~3 seconds instead of serially waiting on dead panels.
    candidates = []
    # Non imporre un tetto artificiale: normalmente il primo batch basta, ma
    # nelle ore affollate devono essere consultabili tutti i 14 gruppi/124
    # account, altrimenti potremmo dichiarare il canale indisponibile pur
    # avendo uno slot libero più avanti nel pool randomizzato.
    for account in accounts:
        aid = '%s://%s/%s' % (account.get('scheme') or 'http', account['host'], account['username'])
        if aid not in excluded:
            candidates.append((account, aid))
    for offset in range(0, len(candidates), 8):
        batch = candidates[offset:offset + 8]
        checked = []
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                pending = dict((executor.submit(_account_free, account), (account, aid))
                               for account, aid in batch)
                for future in as_completed(pending):
                    account, aid = pending[future]
                    free = future.result()
                    if free is not None:
                        checked.append((free, account, aid))
        except Exception:
            for account, aid in batch:
                free = _account_free(account)
                if free is not None:
                    checked.append((free, account, aid))
        checked.sort(key=lambda row: (float(row[0][0]) / max(1, row[0][1]), row[0][0]))
        for free, account, aid in checked:
            stream_id = _account_channel(account, title)
            if not stream_id:
                continue
            scheme = account.get('scheme') or 'http'
            url = '%s://%s/live/%s/%s/%s.ts' % (
                scheme, account['host'], account['username'], account['password'], stream_id)
            if _reachable_url(url):
                logger.info('[IPTV] Group-E slot selected %s (%d/%d)' %
                            (account['host'], free[0], free[1]))
                return url, aid
    return None

def warmup(limit=12):
    """Prepara in background alcuni account liberi per l'avvio rapido.

    Non assegna né prenota slot: legge soltanto stato e palinsesto remoto. La
    disponibilità viene ricontrollata al clic, quindi il dato non può diventare
    una falsa garanzia mentre l'utente resta sulla Home.
    """
    global _warmup_done_at
    now = time.time()
    if _warm_account_ids and now - _warmup_done_at < 30 * 60:
        return len(_warm_account_ids)
    accounts = list(_load_accounts())
    random.shuffle(accounts)
    free = []
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        for offset in range(0, len(accounts), 12):
            batch = accounts[offset:offset + 12]
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                pending = dict((executor.submit(_account_free, account), account)
                               for account in batch)
                for future in as_completed(pending):
                    if future.result() is not None:
                        free.append(pending[future])
            if len(free) >= int(limit):
                break
        free = free[:int(limit)]
        with ThreadPoolExecutor(max_workers=min(6, len(free) or 1)) as executor:
            list(executor.map(lambda account: _account_channel(
                account, '__prippi_warmup__'), free))
    except Exception as exc:
        logger.debug('[IPTV] pool warmup: %s' % exc)
    for account in free:
        _warm_account_ids.add('%s://%s/%s' % (
            account.get('scheme') or 'http', account['host'], account['username']))
    _warmup_done_at = now
    logger.info('[IPTV] pool warmup: %d account pronti' % len(_warm_account_ids))
    return len(_warm_account_ids)

def _reachable_url(url):
    try:
        req = Request(url, headers={'User-Agent': 'VLC/3.0.21 LibVLC/3.0.21',
                                    'Range': 'bytes=0-1023'})
        response = urlopen(req, timeout=5)
        code = getattr(response, 'status', 200)
        response.read(1)
        try: response.close()
        except Exception: pass
        return int(code) in (200, 206)
    except Exception:
        return False

def acquire(title, lease_id, ttl=900, attempt=0):
    catalog = list(_load()); now = time.time(); wanted = str(title or '').casefold().strip()
    # Prefer the complete Group-E pool. Each retry excludes accounts already
    # attempted for this channel, so a playback failure moves to a new list.
    with _lock:
        if int(attempt or 0) == 0:
            _pool_attempts[wanted] = []
        excluded = list(_pool_attempts.get(wanted, []))
    pooled = _pool_url(title, '%s#%s' % (lease_id, attempt), excluded=excluded)
    if pooled:
        url, aid = pooled
        with _lock:
            _pool_attempts.setdefault(wanted, []).append(aid)
            _leases[url] = (now + max(60, int(ttl)), lease_id)
        return url
    # Validate fallback transport streams before leasing them. IPTV lists often
    # retain expired credentials; without this check Kodi opens the first dead
    # URL and never gets a chance to try the next provider slot.
    def _candidates(url):
        """Return the catalog URL plus the currently equivalent IPTV slot.

        The first Peter-Pan slot can answer 401 while the mirrored stexxino
        slot is live (same stream id and credentials).  Keep this fallback
        local and deterministic; refreshed catalogs may still provide their
        own additional sources.
        """
        out = [url]
        m = re.match(r'^https?://[^/]+/live/4/987654321/(\d+\.ts)$', url, re.I)
        if m:
            out.append('http://9a9p78nt92.stexxino2020.xyz/live/ginevra86/a090922a/' + m.group(1))
        return out
    with _lock:
        for key, lease in list(_leases.items()):
            exp = lease[0] if isinstance(lease, tuple) else lease
            if exp <= now: _leases.pop(key, None)
        for item in catalog:
            if str(item.get('title', '')).casefold().strip() != wanted: continue
            for url in item.get('sources') or []:
                # Cached TheGroove links may contain Kodi pipe headers.  Keep
                # only the transport URL here; the resolver supplies headers.
                clean_url = str(url).split('|', 1)[0].strip()
                if not clean_url:
                    continue
                for candidate in _candidates(clean_url):
                    active = _leases.get(candidate)
                    if active is not None:
                        # Re-entry of the same logical session is allowed.
                        if isinstance(active, tuple) and active[1] == lease_id:
                            _leases[candidate] = (now + max(60, int(ttl)), lease_id)
                            return candidate
                        continue
                    if not _reachable_url(candidate):
                        continue
                    _leases[candidate] = (now + max(60, int(ttl)), lease_id)
                    return candidate
    return None

def release(url):
    if url:
        with _lock: _leases.pop(url, None)

def logo_for(title, fallback=''):
    """Return a cached local logo, downloading a public match once if needed."""
    safe = re.sub(r'[^a-z0-9]+', '_', str(title or '').lower()).strip('_')
    if not safe:
        return fallback or ''
    try:
        root = os.path.join(config.get_data_path(), 'iptv_logos')
        os.makedirs(root, exist_ok=True)
        for ext in ('.png', '.jpg', '.jpeg', '.webp'):
            local = os.path.join(root, safe + ext)
            if os.path.isfile(local) and os.path.getsize(local) > 100:
                return local
        global _logo_index
        if _logo_index is None:
            req = Request('https://iptv-org.github.io/api/channels.json',
                          headers={'User-Agent': 'PrippiStream/2.x'})
            with urlopen(req, timeout=8) as resp:
                _logo_index = json.loads(resp.read().decode('utf-8'))
        needle = re.sub(r'[^a-z0-9]+', '', str(title or '').lower())
        match = next((x for x in (_logo_index or [])
                      if re.sub(r'[^a-z0-9]+', '', str(x.get('name','')).lower()) == needle
                      and x.get('logo')), None)
        remote = (match or {}).get('logo', '') if match else (fallback or '')
        if remote:
            ext = os.path.splitext(remote.split('?', 1)[0])[1].lower()
            if ext not in ('.png', '.jpg', '.jpeg', '.webp'): ext = '.png'
            local = os.path.join(root, safe + ext)
            with urlopen(Request(remote, headers={'User-Agent': 'PrippiStream/2.x'}), timeout=8) as resp:
                data = resp.read()
            if len(data) > 100:
                open(local, 'wb').write(data)
                return local
    except Exception as exc:
        logger.debug('[IPTV] logo %s: %s' % (title, exc))
    return fallback or ''
