"""Local admission administration; credentials never enter the browser app."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Admission:
    code: str
    name: str = ''
    phone: str = ''
    email: str = ''
    status: str | None = None
    checked_in_at: str | None = None
    in_csv: bool = False
    in_db: bool = False

    @property
    def label(self) -> str:
        if not self.in_db:
            return 'DB 미등록'
        return {'pending': '미입장', 'checked_in': '입장 완료', None: '미입장'}.get(
            self.status, '알 수 없는 상태')

    @property
    def local_time(self) -> str:
        if not self.checked_in_at:
            return ''
        try:
            value = datetime.fromisoformat(self.checked_in_at.replace('Z', '+00:00'))
            if value.tzinfo is None:
                return self.checked_in_at
            return value.astimezone(ZoneInfo('Australia/Sydney')).strftime('%Y-%m-%d %H:%M:%S %Z')
        except ValueError:
            return self.checked_in_at


def matches(row: Admission, keyword: str) -> bool:
    query = keyword.strip().casefold()
    if not query:
        return True
    if any(query in value.casefold() for value in (row.name, row.phone, row.email, row.code)):
        return True
    digits = re.sub(r'\D', '', query)
    return bool(digits and re.fullmatch(r'[+\d\s().-]+', query)
                and digits in re.sub(r'\D', '', row.phone))


def join_registrations(path: Path, states: list[dict]) -> list[Admission]:
    database = {row['bar_code']: row for row in states}
    result = []
    seen = set()
    with path.open(encoding='utf-8-sig', newline='') as source:
        reader = csv.reader(source)
        headers = next(reader)
        code_column = next((i for i, header in enumerate(headers)
                            if re.sub(r'[\s_]', '', header.lower()) == 'qrcodes'), None)
        if code_column is None:
            raise ValueError('CSV에 Qr_Codes 열이 없습니다.')
        for number, values in enumerate(reader, 2):
            if not any(value.strip() for value in values):
                continue
            if len(values) <= max(code_column, 3):
                raise ValueError(f'CSV {number}행의 필드가 부족합니다.')
            code = values[code_column].strip()
            if not code or code in seen:
                raise ValueError(f'CSV {number}행의 바코드가 없거나 중복됩니다.')
            seen.add(code)
            state = database.get(code, {})
            result.append(Admission(code, values[1].strip(), values[3].strip(),
                                    values[2].strip(), state.get('status'),
                                    state.get('checked_in_at'), True, code in database))
    for code, state in database.items():
        if code not in seen:
            result.append(Admission(code, '(CSV 미등록)', status=state.get('status'),
                                    checked_in_at=state.get('checked_in_at'), in_db=True))
    return result


def public_config() -> tuple[str, str]:
    config = (ROOT / 'supabase-config.js').read_text()
    url = re.search(r"url:\s*'([^']+)'", config)
    key = re.search(r"publishableKey:\s*'([^']+)'", config)
    if not url or not key or not url[1] or not key[1]:
        raise ValueError('supabase-config.js의 URL과 공개 키를 확인해 주세요.')
    return url[1], key[1]


def is_admin_key(key: str) -> bool:
    if key.startswith('sb_secret_'):
        return True
    # Legacy service_role JWT; only inspect the role, the server verifies it.
    try:
        import base64
        payload = key.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return claims.get('role') == 'service_role'
    except (ValueError, IndexError, TypeError, AttributeError):
        return False


class AdmissionBackend:
    def __init__(self, url: str, key: str, *, admin: bool = False,
                 csv_path: Path = ROOT / 'registrations.csv'):
        if admin and not is_admin_key(key):
            raise ValueError('관리 모드에는 Secret key 또는 service_role 키가 필요합니다.')
        self.url = url.rstrip('/')
        self.key = key
        self.admin = admin
        self.csv_path = csv_path

    def request(self, method: str, path: str, payload=None):
        headers = {'apikey': self.key, 'Accept': 'application/json'}
        # Legacy service-role JWTs use Bearer auth; new sb_secret keys use apikey.
        if self.key.startswith('eyJ'):
            headers['Authorization'] = 'Bearer ' + self.key
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers.update({'Content-Type': 'application/json', 'Prefer': 'return=minimal'})
        req = urllib.request.Request(self.url + '/rest/v1/' + path, data=body,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors='replace').replace(self.key, '[redacted]')
            raise RuntimeError(f'Supabase HTTP {error.code}: {detail}') from None
        except urllib.error.URLError as error:
            raise RuntimeError('Supabase 연결 실패: ' + str(error.reason).replace(self.key, '[redacted]')) from None

    def load(self) -> list[Admission]:
        states = []
        offset = 0
        while True:
            page = self.request('GET', 'checkins?select=bar_code,status,checked_in_at'
                                f'&order=bar_code&limit=500&offset={offset}')
            states.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
        return join_registrations(self.csv_path, states)

    def reset(self, code: str | None = None) -> None:
        if not self.admin:
            raise PermissionError('조회 전용입니다. --admin 옵션으로 실행해 주세요.')
        if code is not None and not code.strip():
            raise ValueError('초기화할 바코드가 없습니다.')
        # One database statement; reset ALL database rows, not just CSV/search matches.
        selector = 'not.is.null' if code is None else 'eq.' + urllib.parse.quote(code, safe='')
        self.request('PATCH', 'checkins?bar_code=' + selector,
                     {'status': 'pending', 'checked_in_at': None})
