#!/usr/bin/env python3
"""build-locale.py — extract _("strings") from JS source, compile .mo files.

Usage:
    python3 build-locale.py extract    # regenerate po/appmenu.pot
    python3 build-locale.py compile    # compile all .po → locale/*/LC_MESSAGES/*.mo
    python3 build-locale.py all        # extract + compile
"""
import os, re, struct, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_GLOB = '*.js'
SKIP_DIRS = {'.git', 'dist', 'Downloads', 'locale', 'po', '__pycache__', 'node_modules'}


def find_js_files():
    files = []
    for root, dirs, fnames in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in fnames:
            if fn.endswith('.js'):
                files.append(os.path.join(root, fn))
    return sorted(files)


def extract():
    """Extract _("...") strings and write po/appmenu.pot."""
    strings = set()
    for path in find_js_files():
        with open(path, 'r') as f:
            content = f.read()
        for m in re.finditer(r"\b_\(\s*(['\"])((?:\\.|(?!\1).)*?)\1\s*\)", content):
            s = m.group(2)
            s = s.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
            if s.strip():
                strings.add(s)

    pot_path = os.path.join(ROOT, 'po', 'appmenu.pot')
    os.makedirs(os.path.dirname(pot_path), exist_ok=True)

    with open(pot_path, 'w') as f:
        f.write('# AppMenu translation template.\n')
        f.write('#\n')
        f.write('msgid ""\nmsgstr ""\n')
        f.write('"Project-Id-Version: AppMenu\\n"\n')
        f.write('"POT-Creation-Date: 2026-07-25 06:58+0000\\n"\n')
        f.write('"PO-Revision-Date: AUTO\\n"\n')
        f.write('"Last-Translator: AUTO\\n"\n')
        f.write('"Language-Team: none\\n"\n')
        f.write('"MIME-Version: 1.0\\n"\n')
        f.write('"Content-Type: text/plain; charset=UTF-8\\n"\n')
        f.write('"Content-Transfer-Encoding: 8bit\\n"\n')
        f.write('\n')
        for s in sorted(strings):
            esc = s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
            f.write(f'msgid "{esc}"\n')
            f.write('msgstr ""\n')
            f.write('\n')

    print(f'Extracted {len(strings)} unique strings into po/appmenu.pot')


def _unescape(s):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            n = s[i + 1]
            out.append({'n': '\n', 't': '\t', '"': '"', '\\': '\\'}.get(n, '\\' + n))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def parse_po(po_path):
    """Parse a .po file into {msgid: msgstr}. Supports multi-line strings."""
    entries = {}
    cur = None      # 'id' or 'str'
    mid = mstr = None
    fuzzy = False

    def flush():
        nonlocal mid, mstr, fuzzy
        if mid is not None and mstr is not None and not fuzzy:
            entries[mid] = mstr
        mid = mstr = None
        fuzzy = False

    with open(po_path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if line.startswith('#,') and 'fuzzy' in line:
                flush()
                fuzzy = True
                continue
            if line.startswith('#') or not line:
                continue
            if line.startswith('msgid '):
                if mstr is not None:
                    flush()
                mid = _unescape(line[6:].strip()[1:-1])
                cur = 'id'
            elif line.startswith('msgstr '):
                mstr = _unescape(line[7:].strip()[1:-1])
                cur = 'str'
            elif line.startswith('"') and cur:
                part = _unescape(line[1:-1])
                if cur == 'id':
                    mid += part
                else:
                    mstr += part
        flush()
    return entries


def compile_mo(po_path):
    """Compile a single .po file to .mo. Returns number of translated entries."""
    parsed = parse_po(po_path)
    entries = {k: v for k, v in parsed.items() if k and v}   # skip empty/untranslated
    # The header entry (empty msgid) tells gettext the charset
    entries[''] = ('Content-Type: text/plain; charset=UTF-8\n'
                   'Content-Transfer-Encoding: 8bit\n')
    items = sorted((k.encode('utf-8'), v.encode('utf-8')) for k, v in entries.items())
    n = len(items)

    # Binary .mo layout (little-endian is fine: magic is detected by readers)
    keys_start = 28 + n * 16
    ids = b''
    strs = b''
    id_table = []
    str_table = []
    for k, v in items:
        id_table.append((len(k), keys_start + len(ids)))
        ids += k + b'\x00'
    values_start = keys_start + len(ids)
    for k, v in items:
        str_table.append((len(v), values_start + len(strs)))
        strs += v + b'\x00'

    mo_dir = os.path.join(ROOT, 'locale', os.path.splitext(os.path.basename(po_path))[0], 'LC_MESSAGES')
    os.makedirs(mo_dir, exist_ok=True)
    mo_path = os.path.join(mo_dir, 'appmenu.mo')

    with open(mo_path, 'wb') as f:
        f.write(struct.pack('<7I', 0x950412de, 0, n, 28, 28 + n * 8, 0, 0))
        for length, offset in id_table:
            f.write(struct.pack('<II', length, offset))
        for length, offset in str_table:
            f.write(struct.pack('<II', length, offset))
        f.write(ids)
        f.write(strs)

    return n - 1


def compile_all():
    """Compile all .po files under po/."""
    po_dir = os.path.join(ROOT, 'po')
    if not os.path.isdir(po_dir):
        print('No po/ directory — nothing to compile.')
        return

    total = 0
    for entry in os.listdir(po_dir):
        fpath = os.path.join(po_dir, entry)
        if os.path.isfile(fpath) and fpath.endswith('.po'):
            n = compile_mo(fpath)
            rel = os.path.relpath(fpath, ROOT)
            lc = os.path.splitext(entry)[0]
            print(f'  locale/{lc}/LC_MESSAGES/appmenu.mo  ({n} strings)')
            total += n

    print(f'\nCompiled {total} total message(s).')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if cmd in ('extract', 'all'):
        extract()
    if cmd in ('compile', 'all'):
        compile_all()
    if cmd not in ('extract', 'compile', 'all'):
        print(f'Unknown command: {cmd}')
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
