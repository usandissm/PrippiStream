# -*- coding: utf-8 -*-
"""Local event calendar and persistent team-badge cache; no playback logic."""
import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import quote
from urllib.request import Request, urlopen


def canonical(value):
    value = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().casefold()
    return re.sub(r'[^a-z0-9]', '', value)


ALIASES = {'inter': 'Inter Milan', 'milan': 'AC Milan', 'psg': 'Paris SG',
           'atleticomadrid': 'Atletico Madrid', 'roma': 'AS Roma',
           'wolves': 'Wolverhampton Wanderers', 'suedtirol': 'Sudtirol',
           'vicenzavirtus': 'Vicenza', 'gaziantepbb': 'Gaziantep FK',
           'jeonbuk': 'Jeonbuk Hyundai Motors', 'johordt': 'Johor Darul Ta\'zim',
           'port': 'Port FC', 'petrolul': 'Petrolul Ploiesti',
           'achmat': 'Akhmat Grozny', 'fakel': 'Fakel Voronezh',
           'veres': 'Veres Rivne', 'araz': 'Araz Nakhchivan',
           'alhilalriad': 'Al Hilal',
           'beijingguoan': 'Beijing Guoan'}
ALIASES.update({
    'amburgo': 'Hamburg SV', 'augusta': 'FC Augsburg', 'borussiam': 'Borussia Monchengladbach',
    'colonia': 'FC Cologne', 'eintracht': 'Eintracht Frankfurt', 'magonza05': 'Mainz',
    'rblipsia': 'RB Leipzig', 'werderbrema': 'Werder Bremen', 'unionberlino': 'Union Berlin',
    'rwessen': 'Rot-Weiss Essen', 'grossaspach': 'SG Sonnenhof Grossaspach',
    'dinamozagabria': 'Dinamo Zagreb', 'dinamom': 'Dynamo Moscow', 'slaviapraga': 'Slavia Prague',
    'broendby': 'Brøndby IF', 'denhaag': 'ADO Den Haag', 'miltonkeynes': 'Milton Keynes Dons',
    'cambridgeutd': 'Cambridge United', 'gornikzabrze': 'Gornik Zabrze', 'rakow': 'Rakow Czestochowa',
    'rapidbucarest': 'Rapid Bucuresti', 'motor': 'Motor Lublin', 'recreativodehuelva': 'Recreativo Huelva',
    'sestao': 'Sestao River', 'botosani': 'FC Botosani', 'karlsruhe': 'Karlsruher SC',
    'hartberg': 'TSV Hartberg', 'firstvienna': 'First Vienna FC 1894',
    'levski': 'Levski Sofia', 'buducnost': 'Buducnost Podgorica',
    'independienter': 'Independiente Rivadavia', 'puertocabello': 'Academia Puerto Cabello',
})
WIKI_BADGES = {
    'potenza': ('it', 'Potenza Calcio'), 'teamaltamura': ('it', 'Team Altamura'),
    'sorrento': ('it', 'Sorrento Calcio 1945'), 'savoia': ('it', 'Savoia 1908'),
    'scafatese': ('it', 'Scafatese Calcio 1922'), 'petrolul': ('en', 'FC Petrolul Ploiești'),
    'asteras': ('en', 'Asteras Tripolis F.C.'), 'panserraikos': ('en', 'Panserraikos F.C.'),
    'nikivolou': ('en', 'Niki Volos F.C.'), 'kifisiafc': ('en', 'A.E. Kifisia F.C.'),
    'daejeoncitizen': ('en', 'Daejeon Hana Citizen'), 'shanghaiport': ('en', 'Shanghai Port F.C.'),
    'ratchaburi': ('en', 'Ratchaburi F.C.'), 'psisleman': ('en', 'PSS Sleman'),
    'psssleman': ('en', 'PSS Sleman'), 'borneo': ('en', 'Borneo F.C. Samarinda'),
    'gornikleczna': ('en', 'Górnik Łęczna'), 'septemvri': ('en', 'PFC Septemvri Sofia'),
    'cernomore': ('en', 'PFC Cherno More Varna'), 'veres': ('en', 'NK Veres Rivne'),
    'livyibereh': ('en', 'FC Livyi Bereh Kyiv'), 'zira': ('en', 'Zira FK'),
    'araz': ('en', 'Araz-Naxçıvan PFK'), 'gabala': ('en', 'Gabala FK'),
    'sabail': ('en', 'Sabail FK'), 'sumqayit': ('en', 'Sumgayit FK'),
    'mingechevir': ('en', 'Mingachevir FK'), 'congan': ('en', 'Cong An Ha Noi FC'),
    'alseeb': ('en', 'Al-Seeb Club'),
    'karsiyaka': ('en', 'Karşıyaka S.K.'), 'etimesgut': ('en', 'Etimesgut Belediyespor'),
    'krka': ('en', 'NK Krka'), 'bilje': ('en', 'ND Bilje'),
    'ilirija': ('en', 'ND Ilirija 1911'), 'brezice': ('en', 'NK Brežice 1919'),
    'jadrandekani': ('en', 'NK Jadran Dekani'), 'progresulspartac': ('en', 'AFC Progresul Spartac București'),
    'miercureaciuc': ('en', 'FK Csíkszereda Miercurea Ciuc'),
    'dynamokyiv': ('en', 'FC Dynamo Kyiv'), 'esteghlalteheran': ('en', 'Esteghlal F.C.'),
    'levadia': ('en', 'FCI Levadia Tallinn'), 'macva': ('en', 'FK Mačva Šabac'),
    'mura': ('en', 'NŠ Mura'), 'ndslovan': ('en', 'ND Slovan'),
    'napredak': ('en', 'FK Napredak Kruševac'), 'narvatrans': ('en', 'JK Narva Trans'),
    'nommeunited': ('en', 'FC Nõmme United'), 'primorje': ('en', 'ND Primorje'),
    'radomlje': ('en', 'NK Radomlje'), 'shababalahli': ('en', 'Shabab Al Ahli Club'),
    'slovanliberec': ('en', 'FC Slovan Liberec'), 'taborsezana': ('en', 'NK Tabor Sežana'),
    'tammeka': ('en', 'Tartu JK Tammeka'), 'teplice': ('en', 'FK Teplice'),
    'shortan': ('en', 'FC Shurtan Guzar'), 'rudar': ('en', 'NK Rudar Velenje'),
    'mazidagi': ('tr', 'Mazıdağı Fosfatspor'),
    canonical('Romania Under-17'): ('en', 'Romania national football team'),
    canonical('Fær Øer Under-17'): ('en', 'Faroe Islands national football team'),
}
WIKI_BADGES.update({
    'arda': ('en', 'FC Arda Kardzhali'),
    'botosani': ('en', 'FC Botoșani'), 'corvinul': ('en', 'CS Corvinul Hunedoara'),
    'utaarad': ('en', 'FC UTA Arad'), 'rapidbucarest': ('en', 'FC Rapid București'),
    'firstvienna': ('en', 'First Vienna FC'), 'hartberg': ('en', 'TSV Hartberg'),
    'gornikzabrze': ('en', 'Górnik Zabrze'), 'motor': ('en', 'Motor Lublin'),
    'rakow': ('en', 'Raków Częstochowa'), 'koper': ('en', 'FC Koper'),
    'maribor': ('en', 'NK Maribor'), 'mornar': ('en', 'FK Mornar'),
    'buducnost': ('en', 'FK Budućnost Podgorica'), 'levski': ('en', 'PFC Levski Sofia'),
    'excelsior31': ('en', "SV Excelsior '31"), 'kloetinge': ('en', 'VV Kloetinge'),
    'koninklijkehfc': ('en', 'Koninklijke HFC'), 'zbrojovkabrno': ('en', 'FC Zbrojovka Brno'),
    'landskrona': ('sv', 'Landskrona BoIS'), 'varberg': ('en', 'Varbergs BoIS'),
    'lionsgibraltar': ('en', 'Lions Gibraltar F.C.'), 'monscalpe': ('en', 'Mons Calpe S.C.'),
    'cuarte': ('en', 'CD Cuarte'), 'manacor': ('es', 'Club Deportivo Manacor'),
    'manresa': ('ca', "Centre d'Esports Manresa"), 'santandreu': ('en', 'UE Sant Andreu'),
    'sestao': ('en', 'Sestao River Club'), 'recreativodehuelva': ('en', 'Recreativo de Huelva'),
    'atleticopinatarense': ('es', 'Club Atlético Pinatarense'),
    'sportingdealcazar': ('es', 'Club de Fútbol Sporting de Alcázar'),
    'alhussein': ('en', 'Al-Hussein SC (Irbid)'), 'alshorta': ('en', 'Al-Shorta SC'),
    'alshamal': ('en', 'Al-Shamal SC'), 'caracas': ('en', 'Caracas FC'),
    'puertocabello': ('en', 'Academia Puerto Cabello'), 'juanpabloii': ('en', 'Juan Pablo II College'),
    'ibis': ('en', 'Íbis Sport Club'),
    'veracruz': ('pt', 'Vera Cruz Futebol Clube (Vitória de Santo Antão)'),
    'rwessen': ('en', 'Rot-Weiss Essen'),
    'grossaspach': ('en', 'SG Sonnenhof Großaspach'),
    'independientedecg': ('en', 'Independiente F.B.C.'),
})
_REVIEWED_CREST_NAMES = {'daejeoncitizen', 'shanghaiport', 'nikivolou', 'veres',
                         'gornikleczna', 'alseeb', 'levadia', 'macva', 'mura',
                         'radomlje', 'ndslovan', 'primorje', 'cernomore', 'rudar', 'mazidagi'}
_REVIEWED_CREST_NAMES.update({'motor', 'maribor', 'kloetinge', 'lionsgibraltar', 'cuarte'})
DIRECT_BADGES = {
    'aral': 'https://aral-pfc.uz/wp-content/fnw-languages/team-logos/aral.png',
    'drenvrhinka': 'https://nkihan.si/wp-content/uploads/2021/11/148_Dren-Vrhnika.jpg',
    'etimesgut': 'https://www.futbollogo.com/resimler/logolar/etimesgutspor.png',
    'mingechevir': 'https://mingachevir-fc.com/wp-content/uploads/2026/04/mingachevir-1.png',
    'simal': 'https://mingachevir-fc.com/wp-content/fnw-languages/team-logos/shimal.png',
    'zaqatala': 'https://mingachevir-fc.com/wp-content/fnw-languages/team-logos/zaqatala.png',
    'savoia': 'https://commons.wikimedia.org/wiki/Special:FilePath/Logo_AC_Savoia_1908_(2022).jpg',
    # National youth/women sides share their national identity. Use country
    # flags rather than fabricating club crests for those teams.
    canonical('Francia (D) Under-17'): 'https://flagcdn.com/w320/fr.png',
    canonical('Francia U16 (D)'): 'https://flagcdn.com/w320/fr.png',
    canonical('Israele (D) Under-17'): 'https://flagcdn.com/w320/il.png',
    canonical('Paesi Bassi (D) Under-17'): 'https://flagcdn.com/w320/nl.png',
    canonical('Stati Uniti U16 (D)'): 'https://flagcdn.com/w320/us.png',
    canonical('Svezia (D) Under-17'): 'https://flagcdn.com/w320/se.png',
    'broendby': 'https://a.espncdn.com/i/teamlogos/soccer/500/575.png',
    'independienter': 'https://a.espncdn.com/i/teamlogos/soccer/500/9744.png',
    'juanpabloii': 'https://a.espncdn.com/i/teamlogos/soccer/500/22534.png',
    'puertocabello': 'https://a.espncdn.com/i/teamlogos/soccer/500/18995.png',
    'corvinul': 'https://fccorvinul1921.ro/wp-content/uploads/2021/12/CorvinulHD.png',
    'excelsior31': 'https://commons.wikimedia.org/wiki/Special:FilePath/Excelsior31_rijssen.png',
    'sportingdealcazar': 'https://sportingdealcazar.com/wp-content/uploads/2020/10/sporting-alcazar-png.png',
    'kuraraz': 'https://r2.thesportsdb.com/images/media/team/badge/9vhsm51731817325.png',
    'atleticopinatarense': 'https://www.ffrm.es/pnfg/pimg/Clubes/00100_0000128594_escudo.jpg',
    'manacor': 'https://r2.thesportsdb.com/images/media/team/badge/fkrmst1735100950.png',
    'landskrona': 'https://thumb.wikimedia.org/wikipedia/commons/thumb/3/36/Landskrona_BoIS.svg/500px-Landskrona_BoIS.svg.png',
    'manresa': 'https://www.dsg-images.com/sport_entity/200x200/6105.png',
}


def _direct_badge(name, path):
    url = DIRECT_BADGES.get(canonical(name))
    if not url:
        return ''
    try:
        with urlopen(Request(url, headers={'User-Agent': 'PrippiStream-event-art/1.0'}), timeout=6) as response:
            data = response.read(2 * 1024 * 1024)
        if data.startswith(b'\xff\xd8\xff'):
            path = path[:-4] + '.jpg'
        elif not data.startswith(b'\x89PNG\r\n\x1a\n'):
            return ''
        with open(path + '.tmp', 'wb') as stream:
            stream.write(data)
        os.replace(path + '.tmp', path)
        return path
    except Exception:
        return ''


def _wiki_badge(name, path):
    page = WIKI_BADGES.get(canonical(name))
    if not page:
        return ''
    language, title = page
    try:
        with urlopen(Request('https://' + language + '.wikipedia.org/api/rest_v1/page/summary/' + quote(title.replace(' ', '_')),
                             headers={'User-Agent': 'PrippiStream-event-art/1.0'}), timeout=5) as response:
            doc = json.loads(response.read(1024 * 1024).decode('utf-8'))
        image = (doc.get('thumbnail') or doc.get('originalimage') or {}).get('source', '')
        # A page image can be a stadium or a player: accept only named crests.
        if not image.startswith('https://') or not (canonical(name) in _REVIEWED_CREST_NAMES or
                re.search(r'logo|stemma|crest|badge|escudo|emblem|marchio|herb', image, re.I)):
            return ''
        with urlopen(Request(image, headers={'User-Agent': 'PrippiStream-event-art/1.0'}), timeout=5) as response:
            data = response.read(2 * 1024 * 1024)
        if data.startswith(b'\xff\xd8\xff'):
            path = path[:-4] + '.jpg'
        elif not data.startswith(b'\x89PNG\r\n\x1a\n'):
            return ''
        with open(path + '.tmp', 'wb') as output:
            output.write(data)
        os.replace(path + '.tmp', path)
        return path
    except Exception:
        return ''


def teams(title):
    parts = re.split(r'\s+(?:vs\.?|v\.)\s+', title, maxsplit=1, flags=re.I)
    # Multiple versus tokens mean ambiguous source metadata: do not guess badges.
    if len(parts) != 2 or re.search(r'\s+vs\s+', parts[-1], re.I):
        return title, ''
    return parts[0].strip(), parts[1].strip()


def initials(name):
    return ''.join(word[0] for word in name.split() if word)[:3].upper() or '?'


def is_multigol(title):
    return bool(re.search(r'multigol|diretta\s*gol|simulcast', title or '', re.I))


def _directory():
    from platformcode import config
    folder = os.path.join(config.get_data_path(), 'event_team_badges')
    os.makedirs(folder, exist_ok=True)
    return folder


def _cached_badge(key):
    folders = [_directory()]
    try:
        from platformcode import config
        folders.append(os.path.join(config.get_runtime_path(), 'resources', 'media', 'event_team_badges'))
    except (AttributeError, ImportError):
        pass
    for folder in folders:
        for extension in ('.png', '.jpg'):
            path = os.path.join(folder, key + extension)
            if os.path.isfile(path):
                return path
    return ''


def badge(name, fetch=False):
    if not name or is_multigol(name):
        return ''
    # Ignore the old misidentified Araz 1983 file. The verified crest reads
    # KUR-ARAZ FK, IMISLI, 2023, and is stored under a new cache identity.
    identity = canonical(name) + ('-verified2023' if canonical(name) == 'kuraraz' else '')
    key = hashlib.sha256(identity.encode()).hexdigest()[:24]
    path = os.path.join(_directory(), key + '.png')
    existing = _cached_badge(key)
    if existing:
        return existing
    alias = ALIASES.get(canonical(name))
    if alias and canonical(alias) != canonical(name):
        # Read-only target lookup (no recursive requests and no alias cycles).
        alias_key = hashlib.sha256(canonical(alias).encode()).hexdigest()[:24]
        existing = _cached_badge(alias_key)
        if existing:
            return existing
    parent_name = re.sub(r'\s+(?:Under[ -]?(?:18|19|20|21|23)|U(?:18|19|20|21|23)|II)$', '', name, flags=re.I)
    if parent_name != name:
        parent_image = badge(parent_name, fetch=False)
        if parent_image:
            return parent_image
    # New lookup generation retries misses made by the old league-only lookup.
    marker = path + '.miss-v4'
    if fetch and canonical(name) in DIRECT_BADGES:
        direct = _direct_badge(name, path)
        if direct:
            return direct
    if not fetch or (os.path.exists(marker) and time.time() - os.path.getmtime(marker) < 86400):
        return ''
    wiki_path = _wiki_badge(name, path)
    if wiki_path:
        return wiki_path
    try:
        query = ALIASES.get(canonical(parent_name), parent_name)
        # Youth/reserve teams use their own parent club crest, never another
        # similarly named club. The exact team label remains on the event.
        parent = re.sub(r'\s+(?:Under[ -]?(?:18|19|20|21|23)|U(?:18|19|20|21|23)|II)$', '', query, flags=re.I)
        if parent != query:
            parent_path = badge(parent, fetch=False)
            if parent_path:
                return parent_path
            query = ALIASES.get(canonical(parent), parent)
        search = Request('https://site.web.api.espn.com/apis/common/v3/search?query=' + quote(query) + '&limit=10&type=team',
                         headers={'User-Agent': 'PrippiStream-event-art/1.0'})
        with urlopen(search, timeout=5) as response:
            search_doc = json.loads(response.read(1024 * 1024).decode('utf-8'))
        for team in search_doc.get('items') or []:
            names = [team.get(k, '') for k in ('displayName', 'name', 'location', 'shortDisplayName')]
            if team.get('sport') != 'soccer' or canonical(query) not in {canonical(n) for n in names}:
                continue
            logos = team.get('logos') or []
            if not logos:
                continue
            with urlopen(Request(logos[0]['href'], headers={'User-Agent': 'PrippiStream-event-art/1.0'}), timeout=5) as response:
                data = response.read(2 * 1024 * 1024)
            if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                continue
            with open(path + '.tmp', 'wb') as output:
                output.write(data)
            os.replace(path + '.tmp', path)
            return path
    except Exception:
        pass
    try:
        query = ALIASES.get(canonical(name), name)
        request = Request('https://www.thesportsdb.com/api/v1/json/123/searchteams.php?t=' + quote(query),
                          headers={'User-Agent': 'PrippiStream-event-art/1.0'})
        with urlopen(request, timeout=5) as response:
            doc = json.loads(response.read(1024 * 1024).decode('utf-8'))
        for team in doc.get('teams') or []:
            names = [team.get('strTeam', ''), team.get('strTeamShort', '')]
            names += (team.get('strAlternate') or '').split(',')
            if team.get('strSport') != 'Soccer' or canonical(query) not in {canonical(n) for n in names}:
                continue
            image = team.get('strBadge') or team.get('strTeamBadge') or ''
            if not image.startswith('https://'):
                continue
            with urlopen(Request(image, headers={'User-Agent': 'PrippiStream-event-art/1.0'}), timeout=5) as response:
                data = response.read(2 * 1024 * 1024)
            if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                continue
            with open(path + '.tmp', 'wb') as output:
                output.write(data)
            os.replace(path + '.tmp', path)
            return path
    except Exception:
        pass
    with open(marker, 'w') as output:
        output.write('no exact football-team badge match')
    return ''


def calendar(event, now=None):
    """Never invent today's date for an undated source event."""
    if now is None:
        from platformcode.eventtime import now_rome
        now = now_rome()
    value = event.get('date') or ''
    clock = event.get('time') or ''
    if not value:
        return ('Orario indicato · ' + clock + ' · data non confermata', None, 2)
    try:
        bits = [int(n) for n in value.split('/')]
        year = bits[2] if len(bits) == 3 else now.year
        if year < 100:
            year += 2000
        hour, minute = [int(n) for n in clock.split(':')]
        start = datetime(year, bits[1], bits[0], hour, minute)
        if len(bits) == 2:
            # Closest year, not "any past day means next year".
            start = min((start.replace(year=now.year + delta) for delta in (-1, 0, 1)),
                        key=lambda d: abs((d - now).total_seconds()))
        if now > start + timedelta(hours=4):
            return ('Orario superato', start, 3)
        day = ('Oggi' if start.date() == now.date() else
               'Domani' if start.date() == (now + timedelta(days=1)).date() else start.strftime('%d/%m'))
        if start <= now:
            return ('ORA IN PROGRAMMA · ' + day + ' ' + clock + ' (Italia)', start, 0)
        if start - now <= timedelta(minutes=30):
            return ('TRA POCO · ' + clock + ' (Italia)', start, 1)
        return ('PROSSIMAMENTE · ' + day + ' · ' + clock + ' (Italia)', start, 1)
    except (ValueError, TypeError, OverflowError):
        return ('Orario da verificare · ' + clock, None, 2)


def event_status(event, now=None, available=None, playing=False):
    """Calculate on every focus/tick, rather than freezing status at row creation."""
    text, start, rank = calendar(event, now)
    state = None
    if available is None:
        route = event.get('calendar_url') or ''
        if route:
            from platformcode import eventcalendar
            state = eventcalendar.verified_state(route)
        available = True if state == 'available' else False if state == 'unavailable' else None
    if playing:
        text = 'IN ONDA · ' + event.get('time', '') + ' (Italia)'
    elif available and text.startswith('PROSSIMAMENTE'):
        text = text.replace('PROSSIMAMENTE', 'COLLEGAMENTO PRONTO', 1)
    label = ('Sorgente Disponibile' if available or playing else
             'Sorgente non disponibile' if available is False else
             'Verifica sorgente…' if state == 'checking' else 'Sorgente da verificare')
    return text + ' · ' + label


def warm_badges(events):
    """Small bounded background pool; never runs on the first-paint path."""
    from concurrent.futures import ThreadPoolExecutor
    names = set()
    for event in prepare(events):
        names.update(n for n in teams(event.get('teams') or '') if n)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda name: badge(name, fetch=True), sorted(names)))


def country_for(league):
    """Prefer explicit country metadata over ambiguous league names (Serie A)."""
    countries = ('Albania', 'Arabia Saudita', 'Argentina', 'Armenia', 'Australia', 'Austria',
                 'Azerbaigian', 'Bahrein', 'Belgio', 'Bielorussia', 'Brasile', 'Bulgaria',
                 'Cile', 'Cina', 'Cipro', 'Colombia', 'Corea del Sud', 'Costa Rica',
                 'Croazia', 'Danimarca', 'EAU', 'Ecuador', 'Egitto', 'Estonia', 'Finlandia',
                 'Francia', 'Georgia', 'Germania', 'Gibilterra', 'Giordania', 'Grecia',
                 'Guatemala', 'India', 'Indonesia', 'Inghilterra', 'Italia', 'Kazakistan',
                 'Marocco', 'Messico', 'Montenegro', 'Norvegia', 'Paesi Bassi', 'Paraguay',
                 'Perù', 'Polonia', 'Portogallo', 'Repubblica Ceca', 'Romania', 'Russia',
                 'Scozia', 'Serbia', 'Singapore', 'Slovacchia', 'Slovena', 'Slovenia',
                 'Spagna', 'Stati Uniti', 'Sudafrica', 'Svezia', 'Svizzera', 'Turchia',
                 'Ucraina', 'Uzbekistan', 'Venezuela')
    prefix = (league or '').split('.', 1)[0].strip()
    for country in countries:
        if canonical(prefix) == canonical(country):
            return {'Slovena': 'Slovenia', 'EAU': 'Emirati Arabi Uniti'}.get(country, country)
    name = canonical(league or '')
    inferred = {'seriea': 'Italia', 'serieb': 'Italia', 'seriec': 'Italia',
                'coppaitalia': 'Italia', 'premierleague': 'Inghilterra',
                'championship': 'Inghilterra', 'premiership': 'Scozia',
                'bundesliga': 'Germania', 'ligue1': 'Francia', 'ligue2': 'Francia',
                'laliga': 'Spagna', 'copadelrey': 'Spagna'}
    return inferred.get(name, 'Internazionali')


def prepare(events, now=None):
    """Hide unsupported-only/expired events and merge duplicate fixtures."""
    result, seen = [], set()
    for raw in events or []:
        event = dict(raw)
        event['sources'] = [s for s in raw.get('sources') or []
                            if isinstance(s, dict) and s.get('kind') in ('hls', 'web')
                            and str(s.get('url') or '').startswith(('http://', 'https://'))]
        if not event['sources'] and not event.get('calendar_url'):
            continue
        status, start, rank = calendar(event, now)
        if rank == 3:
            continue
        identity = (canonical(event.get('teams', '')), canonical(event.get('league', '')),
                    event.get('date', ''), event.get('time', ''))
        if identity in seen:
            target = next(e for e in result if e['_identity'] == identity)
            urls = {s['url'] for s in target['sources']}
            target['sources'] += [s for s in event['sources'] if s['url'] not in urls]
            continue
        seen.add(identity)
        event.update(_identity=identity, _status=status, _rank=rank,
                     _start=start.isoformat() if start else '9999-' + event.get('time', ''))
        result.append(event)
    for event in result:
        event['_country'] = country_for(event.get('league', ''))
    result.sort(key=lambda e: (0 if e['_country'] == 'Italia' else
                               2 if e['_country'] == 'Internazionali' else 1,
                               canonical(e['_country']), e['_start'],
                               canonical(e.get('teams', ''))))
    return result


def competition_key(league):
    """Equivalent qualified/unqualified names, without Italy/Brazil collisions."""
    country = country_for(league)
    prefix, separator, rest = (league or '').partition('.')
    if separator and country_for(prefix.strip()) == country and country != 'Internazionali':
        league = rest
    return country, canonical(league)
