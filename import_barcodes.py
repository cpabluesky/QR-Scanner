"""Prepare barcode-only seed SQL; optionally import using the configured public API.

Usage: python3 import_barcodes.py [--apply]
Existing barcode rows are always preserved, including admission state and time.
"""
import argparse
import csv
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def read_codes():
    with (ROOT / 'registrations.csv').open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        header = next((h for h in reader.fieldnames or []
                       if re.sub(r'[\s_]', '', h.lower()) == 'qrcodes'), None)
        if not header:
            raise ValueError('Qr_Codes column is missing')
        codes = [row[header].strip() for row in reader]
    if not codes or not all(codes) or len(codes) != len(set(codes)):
        raise ValueError('Expected nonempty, unique barcodes')
    return codes


def write_seed(codes):
    values = ',\n'.join("  ('" + code.replace("'", "''") + "')" for code in codes)
    path = ROOT / 'supabase-seed.sql'
    path.write_text(
        '-- Barcode-only import. Existing admission states and times are preserved.\n'
        'begin;\ninsert into public.checkins (bar_code)\nvalues\n' + values +
        '\non conflict (bar_code) do nothing;\ncommit;\n', encoding='utf-8')
    return path


def import_codes(codes):
    config = (ROOT / 'supabase-config.js').read_text()
    url = re.search(r"url:\s*'([^']+)'", config).group(1).rstrip('/')
    key = re.search(r"publishableKey:\s*'([^']+)'", config).group(1)

    def request(path, rows=None):
        headers = {'apikey': key}
        payload = None
        if rows is not None:
            headers.update({'Content-Type': 'application/json',
                            'Prefer': 'resolution=ignore-duplicates,return=minimal,missing=default'})
            payload = json.dumps(rows).encode()
        req = urllib.request.Request(url + '/rest/v1/' + path, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'Supabase HTTP {error.code}: {error.read().decode()}') from None

    def existing_codes():
        existing = set()
        offset = 0
        while True:
            rows = request(f'checkins?select=bar_code&order=bar_code&limit=1000&offset={offset}')
            existing.update(row['bar_code'] for row in rows)
            if len(rows) < 1000:
                return existing
            offset += len(rows)

    before = existing_codes()
    missing = [code for code in codes if code not in before]
    if missing:
        request('checkins?on_conflict=bar_code', [{'bar_code': code} for code in missing])
    after = existing_codes()
    remaining = set(codes) - after
    if remaining:
        raise RuntimeError(f'Import could not be verified: {len(remaining)} barcodes are not visible')
    print(f'Verified all {len(codes)} barcodes. Submitted {len(missing)} missing codes; '
          'existing rows were preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Import via the public Supabase API')
    args = parser.parse_args()
    codes = read_codes()
    path = write_seed(codes)
    print(f'Prepared {len(codes)} unique barcodes in {path.name}.')
    if args.apply:
        try:
            import_codes(codes)
        except (RuntimeError, urllib.error.URLError) as error:
            parser.exit(1, f'{error}\nRun {path.name} in the Supabase SQL Editor instead.\n')
