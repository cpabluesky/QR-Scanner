"""Textual terminal frontend for the Supabase admission database.

Run: python admission_cli.py            (public, read-only)
     python admission_cli.py --admin    (hidden prompt for an administrator key)
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os

try:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static
except ImportError:
    raise SystemExit('먼저 실행해 주세요: python -m pip install -r requirements-cli.txt')

from admission_backend import Admission, AdmissionBackend, matches, public_config


class ResetConfirmation(ModalScreen[bool]):
    CSS = """
    ResetConfirmation { align: center middle; background: $background 70%; }
    #confirm-dialog { width: 66; height: auto; border: thick $error; padding: 1 2; }
    #confirm-dialog Static { height: auto; margin-bottom: 1; }
    #confirm-dialog Horizontal { height: auto; margin-top: 1; }
    #confirm-dialog Button { margin-right: 1; }
    """
    BINDINGS = [('escape', 'cancel', '취소')]

    def __init__(self, description: str, *, all_rows: bool):
        super().__init__()
        self.description = description
        self.phrase = 'RESET ALL' if all_rows else 'RESET'

    def compose(self) -> ComposeResult:
        with Vertical(id='confirm-dialog'):
            yield Static(Text(self.description))
            yield Static(f'미입장(pending), 입장시간 NULL로 변경합니다.\n계속하려면 {self.phrase}을 입력하세요.')
            yield Input(placeholder=self.phrase, id='confirmation')
            with Horizontal():
                yield Button('취소', id='cancel')
                yield Button('초기화 실행', id='confirm', variant='error', disabled=True)

    @on(Input.Changed, '#confirmation')
    def validate_phrase(self, event: Input.Changed) -> None:
        self.query_one('#confirm', Button).disabled = event.value != self.phrase

    @on(Button.Pressed, '#cancel')
    def cancel(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, '#confirm')
    def confirm(self) -> None:
        if self.query_one('#confirmation', Input).value == self.phrase:
            self.dismiss(True)


class AdmissionAdmin(App):
    TITLE = '입장 관리'
    CSS = """
    Screen { layout: vertical; }
    #summary { height: auto; padding: 1 2; background: $primary-background; }
    #filters { height: auto; padding: 1; }
    #search { width: 2fr; margin-right: 1; }
    #state-filter { width: 1fr; }
    #admissions { height: 1fr; }
    #actions { height: auto; padding: 1; }
    #actions Button { margin-right: 1; }
    #message { height: auto; padding: 0 2 1 2; }
    """
    BINDINGS = [('ctrl+r', 'reload', '새로고침'),
                ('slash', 'search', '검색'), ('ctrl+x', 'reset_all', '전체 초기화'),
                ('ctrl+q', 'quit', '종료')]

    def __init__(self, backend: AdmissionBackend, query: str = ''):
        super().__init__()
        self.backend = backend
        self.initial_query = query
        self.rows: list[Admission] = []
        self.visible_rows: list[Admission] = []
        self.busy = False
        self.loaded = False
        self.sub_title = backend.url + (' · 관리 모드' if backend.admin else ' · 조회 전용')

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static('입장현황을 불러오고 있습니다.', id='summary')
        with Horizontal(id='filters'):
            yield Input(value=self.initial_query, placeholder='이름 · 전화번호 · 이메일 · 바코드 검색', id='search')
            yield Select([('전체', 'all'), ('입장 완료', 'checked_in'),
                          ('미입장', 'pending'), ('DB 미등록', 'missing')],
                         value='all', allow_blank=False, id='state-filter')
        yield DataTable(id='admissions', cursor_type='row', zebra_stripes=True)
        with Horizontal(id='actions'):
            yield Button('새로고침', id='reload', variant='primary')
            yield Button('선택 미입장 처리', id='reset-one', disabled=not self.backend.admin)
            yield Button('전체 초기화', id='reset-all', variant='error', disabled=not self.backend.admin)
        yield Static('조회 전용 모드는 --admin으로 다시 실행하면 관리 모드로 전환됩니다.', id='message')
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns('이름', '전화번호', '이메일', '입장상태', '입장시간 (Sydney)', '바코드')
        self.reload_rows()
        self.query_one('#search', Input).focus()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.query_one('#reload', Button).disabled = busy
        for name in ('#reset-one', '#reset-all'):
            self.query_one(name, Button).disabled = busy or not self.backend.admin or not self.loaded

    def message(self, value: str) -> None:
        self.query_one('#message', Static).update(Text(value))

    @work
    async def reload_rows(self) -> None:
        if self.busy:
            return
        self.set_busy(True)
        self.message('Supabase에서 최신 상태를 조회하고 있습니다...')
        try:
            self.rows = await asyncio.to_thread(self.backend.load)
            self.loaded = True
            self.render_rows()
            self.message('최신 상태를 불러왔습니다. / 검색 · Ctrl+R 새로고침 · Ctrl+Q 종료')
        except Exception as error:
            self.message('조회 실패: ' + str(error))
        finally:
            self.set_busy(False)

    def render_rows(self) -> None:
        query = self.query_one('#search', Input).value
        status = self.query_one('#state-filter', Select).value
        self.visible_rows = [row for row in self.rows if matches(row, query) and (
            status == 'all' or (status == 'missing' and not row.in_db) or
            (status == 'pending' and row.in_db and row.status in ('pending', None)) or
            (status == 'checked_in' and row.status == 'checked_in'))]
        table = self.query_one(DataTable)
        table.clear()
        for row in self.visible_rows:
            table.add_row(*(Text(value) for value in
                (row.name, row.phone, row.email, row.label, row.local_time, row.code)), key=row.code)
        registered = sum(row.in_csv for row in self.rows)
        admitted = sum(row.in_csv and row.status == 'checked_in' for row in self.rows)
        percentage = admitted / registered * 100 if registered else 0
        database = sum(row.in_db for row in self.rows)
        missing = sum(row.in_csv and not row.in_db for row in self.rows)
        self.query_one('#summary', Static).update(
            f'입장 {admitted} / 등록 {registered}명 ({percentage:.1f}%) · DB {database}행 · '
            f'DB 미등록 {missing}명 · 검색 결과 {len(self.visible_rows)}명')

    @on(Input.Changed, '#search')
    @on(Select.Changed, '#state-filter')
    def filter_rows(self) -> None:
        if self.is_mounted:
            self.render_rows()

    def action_search(self) -> None:
        self.query_one('#search', Input).focus()

    @on(Button.Pressed, '#reload')
    def action_reload(self) -> None:
        self.reload_rows()

    @on(Button.Pressed, '#reset-all')
    def action_reset_all(self) -> None:
        if self.busy or not self.backend.admin or not self.loaded:
            return
        count = sum(row.in_db for row in self.rows)
        self.push_screen(ResetConfirmation(
            f'{self.backend.url}\nDB 전체 입장 상태를 초기화합니다 (최근 조회 {count}행).\n'
            '현재 검색/상태 필터와 관계없이 CSV에 없는 DB 행도 포함됩니다.', all_rows=True),
            lambda confirmed: self.reset_rows(None) if confirmed else None)

    @on(Button.Pressed, '#reset-one')
    def reset_selected(self) -> None:
        if self.busy or not self.backend.admin or not self.loaded:
            return
        index = self.query_one(DataTable).cursor_row
        if index < 0 or index >= len(self.visible_rows) or not self.visible_rows[index].in_db:
            self.message('DB에 등록된 행을 먼저 선택해 주세요.')
            return
        row = self.visible_rows[index]
        self.push_screen(ResetConfirmation(
            f'{row.name} · {row.code}\n이 등록자를 미입장으로 되돌립니다.', all_rows=False),
            lambda confirmed: self.reset_rows(row.code) if confirmed else None)

    @work
    async def reset_rows(self, code: str | None) -> None:
        if self.busy:
            return
        self.set_busy(True)
        self.message('초기화를 처리하고 있습니다...')
        try:
            await asyncio.to_thread(self.backend.reset, code)
            self.message('초기화 요청 성공. 최신 상태를 다시 조회하고 있습니다...')
            self.rows = await asyncio.to_thread(self.backend.load)
            self.render_rows()
            self.message('초기화 후 DB 상태를 불러왔습니다. 웹 앱에는 다음 동기화 때 반영됩니다.')
        except Exception as error:
            self.message('처리 결과를 확인해 주세요: ' + str(error) + ' · 새로고침으로 DB 상태를 확인하세요.')
        finally:
            self.set_busy(False)


def main() -> None:
    parser = argparse.ArgumentParser(description='등록자 CSV와 Supabase 입장 상태를 조인하는 터미널 관리 도구')
    parser.add_argument('--admin', action='store_true', help='전체/선택 초기화 허용; 관리자 키는 숨김 입력')
    parser.add_argument('--search', default='', help='시작 시 이름, 전화번호, 이메일, 바코드 필터')
    parser.add_argument('--list', action='store_true', help='대화형 화면 대신 검색 결과를 표로 출력')
    args = parser.parse_args()
    try:
        url, key = public_config()
        if args.admin:
            key = os.environ.get('SUPABASE_ADMIN_KEY') or getpass.getpass('Supabase Secret key (화면에 표시되지 않음): ')
        backend = AdmissionBackend(url, key, admin=args.admin)
        if args.list:
            table = Table('이름', '전화번호', '이메일', '상태', '입장시간 (Sydney)', '바코드')
            for row in backend.load():
                if matches(row, args.search):
                    table.add_row(*(Text(value) for value in
                        (row.name, row.phone, row.email, row.label, row.local_time, row.code)))
            Console().print(table)
        else:
            AdmissionAdmin(backend, args.search).run()
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f'{error}\n')
    except (KeyboardInterrupt, EOFError):
        parser.exit(0, '\n취소했습니다.\n')


if __name__ == '__main__':
    main()
