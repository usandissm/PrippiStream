# PrippiStream: il supporto ES6 di js2py (babel.py, ~3.8 MB di transpiler
# Babel incorporato) e' stato rimosso per alleggerire l'addon. Nessun
# canale/server usa eval_js6/translate_js6 (solo eval_js/EvalJs ES5).
# Per ripristinarlo: recuperare js2py/es6/babel.py dal pacchetto js2py
# upstream e ripristinare questo file.

INITIALISED = False
babel = None
babelPresetEs2015 = None


def js6_to_js5(code):
    raise NotImplementedError(
        'js2py ES6/babel support was removed from PrippiStream to reduce addon size. '
        'Restore lib/js2py/es6/babel.py from upstream js2py if needed.')
