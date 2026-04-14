import os

replacements = [
    ("dialog_ok('S4Me'", "dialog_ok('PrippiStream'"),
    ('dialog_ok("S4Me"', 'dialog_ok("PrippiStream"'),
    ("dialog_yesno('S4Me'", "dialog_yesno('PrippiStream'"),
    ('dialog_yesno("S4Me"', 'dialog_yesno("PrippiStream"'),
    ('S4Me_video_library', 'PrippiStream_video_library'),
    ('keymaps/s4me.xml', 'keymaps/prippistream.xml'),
    ('S4Me environment variables', 'PrippiStream environment variables'),
    ('# to better disguise S4Me as a browser', '# to better disguise PrippiStream as a browser'),
    ('item IS already managed by S4Me', 'item IS already managed by PrippiStream'),
    ("perform the S4Me's", "perform the PrippiStream's"),
    ("in S4Me's window", "in PrippiStream's window"),
    ("'s4me' in filePath", "'prippistream' in filePath"),
    ('# S4Me favorites', '# PrippiStream favorites'),
    ('Class to load and save in the S4Me Favorites', 'Class to load and save in the PrippiStream Favorites'),
    ('report_title=\'S4Me Test Suite\'', 'report_title=\'PrippiStream Test Suite\''),
    ('S4ME_TST_CH', 'PRIPPISTREAM_TST_CH'),
    ('Migrazione KoD -> S4Me', 'Migrazione KoD -> PrippiStream'),
    ('videoteca di S4Me', 'videoteca di PrippiStream'),
    ("'S4Me'", "'PrippiStream'"),
    # README/CONTRIBUTING
    ('# Stream4Me', '# PrippiStream'),
    ('stream4me.github.io', 'usandissm.github.io/PrippiStream'),
    ('https://github.com/stream4me/addon', 'https://github.com/usandissm/PrippiStream'),
    ('https://github.com/Stream4me/addon', 'https://github.com/usandissm/PrippiStream'),
    ('S4Me, alla fine', 'PrippiStream, alla fine'),
    ('S4Me, come Alfa', 'PrippiStream, come Alfa'),
    ('legato a S4Me', 'legato a PrippiStream'),
    ("l'ultima versione di S4Me", "l'ultima versione di PrippiStream"),
    ('funzionamento di S4Me', 'funzionamento di PrippiStream'),
    ("'wstream.py'", "'wstream.py'"),
    ('# Stream4Me\n', '# PrippiStream\n'),
    # specials/help.py
    ('https://github.com/stream4me/addon/wiki/Guida-alle-funzioni-di-S4Me', 'https://github.com/usandissm/PrippiStream'),
    # specials/setting.py
    ("url='https://github.com/stream4me/addon/issues'", "url='https://github.com/usandissm/PrippiStream/issues'"),
    # wstream.py
    ('# Stream4Me', '# PrippiStream'),
    # addonfavorites API
    ("'https://api.github.com/repos/Stream4me/media/git/trees/b36040432b9be120f04e986277fd34f09dcdb4db'",
     "'https://api.github.com/repos/usandissm/PrippiStream/git/trees/HEAD'"),
    # channelselector migrate
    ('Migrazione KoD -> S4Me', 'Migrazione KoD -> PrippiStream'),
    # logger prefix
]

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root_dir)

SKIP_DIRS = {'.git', 'docs', 'tools', '__pycache__'}
SKIP_FILES = {'fix_s4me_refs.py'}

total = 0
for dirpath, dirs, filenames in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for fname in filenames:
        if fname in SKIP_FILES:
            continue
        if not fname.endswith(('.py', '.xml', '.json', '.md', '.txt', '.yml')):
            continue
        fpath = os.path.join(dirpath, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            new_content = content
            for old, new in replacements:
                new_content = new_content.replace(old, new)
            if new_content != content:
                with open(fpath, 'w', encoding='utf-8', errors='ignore') as f:
                    f.write(new_content)
                print('Fixed: ' + fpath)
                total += 1
        except Exception as e:
            print('ERROR ' + fpath + ': ' + str(e))

print('Totale file modificati: ' + str(total))
