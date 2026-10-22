"""Backend and headless terminal UI tests. No live database writes."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from admission_backend import Admission, AdmissionBackend, ROOT, join_registrations, matches
from admission_cli import AdmissionAdmin, ResetConfirmation
from textual.widgets import Button, DataTable, Input, Select, Static


class BackendTests(unittest.TestCase):
    def test_real_csv_joins_by_exact_barcode(self):
        rows = join_registrations(ROOT / 'registrations.csv', [
            {'bar_code':'3PINXMIKmdWm','status':'checked_in','checked_in_at':'2026-10-22T11:00:00Z'}])
        self.assertEqual(len(rows), 401)
        person = next(row for row in rows if row.code == '3PINXMIKmdWm')
        self.assertTrue(person.name and person.phone and person.email)
        self.assertEqual(person.label, '입장 완료')
        self.assertEqual(person.local_time, '2026-10-22 22:00:00 AEDT')
        self.assertEqual(sum(row.in_db for row in rows), 1)
        self.assertEqual(sum(row.label == 'DB 미등록' for row in rows), 400)

    def test_db_only_rows_remain_visible(self):
        rows = join_registrations(ROOT / 'registrations.csv', [
            {'bar_code':'db-only','status':'pending','checked_in_at':None}])
        row = next(row for row in rows if row.code == 'db-only')
        self.assertFalse(row.in_csv)
        self.assertTrue(row.in_db)

    def test_duplicate_or_missing_codes_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'invalid.csv'
            file.write_text('timestamp,name,email,phone,Qr_Codes\n1,A,a@b.c,123,X\n2,B,b@b.c,456,X\n')
            with self.assertRaisesRegex(ValueError, '중복'):
                join_registrations(file, [])

    def test_search_matches_all_relevant_fields(self):
        row = Admission('3PINXMIKmdWm', '승현 Alice', '0401 239 857', 'hello@EXAMPLE.com')
        for query in ('alice', '승', '401239', '@example.COM', '3PINX'):
            self.assertTrue(matches(row, query), query)
        self.assertFalse(matches(row, 'not-here'))
        self.assertTrue(matches(row, ''))

    def test_public_key_cannot_reset(self):
        backend = AdmissionBackend('https://example.supabase.co', 'public')
        backend.request = Mock()
        with self.assertRaises(PermissionError):
            backend.reset()
        backend.request.assert_not_called()

    def test_reset_all_is_one_statement_and_clears_time(self):
        backend = AdmissionBackend('https://example.supabase.co', 'sb_secret_test', admin=True)
        backend.request = Mock()
        backend.reset()
        backend.request.assert_called_once_with('PATCH', 'checkins?bar_code=not.is.null',
                                                {'status':'pending','checked_in_at':None})

    def test_selected_reset_is_scoped_and_escaped(self):
        backend = AdmissionBackend('https://example.supabase.co', 'sb_secret_test', admin=True)
        backend.request = Mock()
        backend.reset('code&x=y')
        backend.request.assert_called_once_with('PATCH', 'checkins?bar_code=eq.code%26x%3Dy',
                                                {'status':'pending','checked_in_at':None})
        with self.assertRaises(ValueError):
            backend.reset('')

    def test_reads_paginate(self):
        backend = AdmissionBackend('https://example.supabase.co', 'public')
        page = [{'bar_code':f'code{i}', 'status':'pending','checked_in_at':None} for i in range(500)]
        backend.request = Mock(side_effect=[page, []])
        rows = backend.load()
        self.assertEqual(backend.request.call_count, 2)
        self.assertIn('offset=500', backend.request.call_args.args[1])
        self.assertEqual(sum(row.in_db for row in rows), 500)


class FakeBackend:
    url = 'https://example.supabase.co'

    def __init__(self, admin=True):
        self.admin = admin
        self.calls = []
        self.rows = [
            Admission('A', 'Alice', '0401 239 857', 'alice@example.com', 'checked_in',
                      '2026-10-22T11:00:00Z', True, True),
            Admission('B', 'Bob', '0411-222-333', 'bob@example.net', 'pending', None, True, True),
            Admission('C', '(CSV 미등록)', status='checked_in',
                      checked_in_at='2026-10-22T11:00:00Z', in_db=True)
        ]

    def load(self):
        return list(self.rows)

    def reset(self, code=None):
        if not self.admin:
            raise PermissionError('read only')
        self.calls.append(code)
        self.rows = [replace(row,status='pending',checked_in_at=None)
                     if code is None or row.code == code else row for row in self.rows]


class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def ready(self, app, pilot):
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_search_filter_and_read_only_mode(self):
        backend = FakeBackend(admin=False)
        app = AdmissionAdmin(backend)
        async with app.run_test(size=(130, 40)) as pilot:
            await self.ready(app,pilot)
            self.assertEqual(app.query_one(DataTable).row_count, 3)
            app.query_one('#search', Input).value = '401239'
            await pilot.pause()
            self.assertEqual([row.code for row in app.visible_rows], ['A'])
            app.query_one('#search', Input).value = ''
            app.query_one('#state-filter', Select).value = 'pending'
            await pilot.pause()
            self.assertEqual([row.code for row in app.visible_rows], ['B'])
            self.assertTrue(app.query_one('#reset-all', Button).disabled)
            self.assertTrue(app.query_one('#reset-one', Button).disabled)
            app.action_reset_all()
            self.assertNotIsInstance(app.screen, ResetConfirmation)
            self.assertEqual(backend.calls, [])

    async def test_reset_all_requires_phrase_and_ignores_search_filter(self):
        backend = FakeBackend()
        app = AdmissionAdmin(backend, 'Alice')
        async with app.run_test(size=(80, 24)) as pilot:
            await self.ready(app,pilot)
            self.assertEqual(len(app.visible_rows),1)
            await pilot.click('#reset-all')
            self.assertIsInstance(app.screen, ResetConfirmation)
            self.assertTrue(app.screen.query_one('#confirm',Button).disabled)
            app.screen.query_one(Input).value = 'RESET'
            await pilot.pause()
            self.assertTrue(app.screen.query_one('#confirm',Button).disabled)
            app.screen.query_one(Input).value = 'RESET ALL'
            await pilot.pause()
            await pilot.click('#confirm')
            await self.ready(app,pilot)
            self.assertEqual(backend.calls,[None])
            self.assertTrue(all(row.status == 'pending' and row.checked_in_at is None for row in backend.rows))

    async def test_cancel_never_writes_and_selected_reset_only_changes_one_row(self):
        backend = FakeBackend()
        app = AdmissionAdmin(backend, 'Alice')
        async with app.run_test(size=(130, 40)) as pilot:
            await self.ready(app,pilot)
            await pilot.click('#reset-all')
            await pilot.click('#cancel')
            self.assertEqual(backend.calls,[])
            await pilot.click('#reset-one')
            app.screen.query_one(Input).value = 'RESET'
            await pilot.pause()
            await pilot.click('#confirm')
            await self.ready(app,pilot)
            self.assertEqual(backend.calls,['A'])
            self.assertEqual(backend.rows[0].status,'pending')
            self.assertEqual(backend.rows[2].status,'checked_in')


if __name__ == '__main__':
    unittest.main()
