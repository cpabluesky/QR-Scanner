# QR-Scanner
QR Scanner - For 2026 Dharma Talk

## Connect Supabase (public access, no login)

Registration details remain in `registrations.csv`. Admission state is shared in
Supabase, so multiple devices can read and check in at the same time. Visitors
do not need a Supabase account or an app login.
Visible registration cards and search results refresh from the DB every
five seconds while the page is visible, and when the window regains focus.
Scanning, searching, and choosing a search result also read current DB status.
Check-in always uses the atomic DB function, regardless of the last refresh.
The top-right 입장현황 panel shows the admitted count, registered count (currently
401), and percentage, refreshing every five seconds while open. Search matches
case-insensitive fragments anywhere in name, phone, or email, including phone
digits across spaces and hyphens.

1. Run [`supabase-setup.sql`](supabase-setup.sql) in your project's SQL Editor.
   It creates the table/function, or switches the earlier staff-only setup to
   public access without resetting existing admissions. Operator accounts and
   `scanner_staff` membership are no longer needed. An existing `scanner_staff`
   table is left in place but is not used.
2. Run [`supabase-seed.sql`](supabase-seed.sql) in the SQL Editor to import the
   401 prepared barcodes while preserving existing rows. Regenerate this file
   after CSV changes with `python3 import_barcodes.py`. Alternatively, import a
   UTF-8 CSV containing only `bar_code` into `public.checkins` through
   the Table Editor. Use exact case-sensitive `Qr_Codes` values from
   `registrations.csv`. Omit other columns to apply the defaults: `pending` and
   NULL. To preserve existing Google Sheets admissions, migrate those rows with
   `status=checked_in` and their original timezone-qualified admission times.
   For later registrations, insert only new codes; preserve existing statuses.
   The public browser key intentionally cannot insert records, so
   `python3 import_barcodes.py --apply` requires an existing API INSERT grant and
   will be refused by the recommended public-access setup. Use the SQL Editor
   for imports rather than granting public INSERT access.
3. Enter the Project URL and public Publishable key in
   [`supabase-config.js`](supabase-config.js):

   ```js
   window.SUPABASE_CONFIG = {
     url: 'https://YOUR-PROJECT.supabase.co',
     publishableKey: 'sb_publishable_YOUR_PUBLIC_KEY'
   };
   ```

   A legacy `anon` key also works. Never enter a secret/service_role key or DB
   password. No Authentication or redirect URL settings are needed for this app.
4. Serve locally with `python3 -m http.server 8000` and open
   `http://localhost:8000`. Test before publishing the updated files to GitHub
   Pages. Remote camera access needs HTTPS, as provided by GitHub Pages.

## Public permissions

The public `anon` role may read barcode/status/time and execute `check_in`.
Direct INSERT, UPDATE, and DELETE are not granted. The function only admits
an existing barcode and preserves the first admission time on repeated or
simultaneous requests. DB timestamps are displayed in `Australia/Sydney`.

Anyone who can access the public API can read these admission records and mark
known barcodes as admitted. Possessing the webpage URL is not an access-control
boundary. There are no visitor accounts or logins in this implementation.

## Verify

Run `python3 tests/run_tests.py` for mocked JavaScript integration tests using
Node.js or macOS JavaScriptCore. Also verify against the actual Supabase project:

- Open an incognito window: scan/search must work without signing in.
- Scan `3PINXMIKmdWm` and verify its current DB status.
- With a designated test registration, check in on one device and scan it on
  a second. Both devices should see the original DB admission time.
- Try simultaneous admission on two devices. One reports a new admission; the
  other reports already admitted, with the same timestamp.
- Disconnect the network: no admission success should be displayed on error.
  Reconnect and scan again to resolve requests that may have reached the DB.
- Check that direct public INSERT, UPDATE, and DELETE requests are denied.

The app no longer calls Google Apps Script. Update the registration CSV in the
repository to change the registration list and preserve its `Qr_Codes` column.
New registration codes must also be imported into Supabase before admission.
CSV changes do not reset DB admission state.

## 터미널 관리 화면 (Textual CLI)

이름·전화번호·이메일·바코드로 검색하며, `registrations.csv`의 등록자 정보와
Supabase의 입장 상태를 바코드로 조인해서 표시합니다. CSV에만 있는 행은
`DB 미등록`, DB에만 있는 행은 `CSV 미등록`으로 표시합니다.

프로젝트 폴더에서 처음 한 번 설치합니다 (Python 3.10 이상):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cli.txt
```

조회 전용 화면 실행:

```sh
.venv/bin/python admission_cli.py
```

짧은 실행 명령으로 `./admission-admin`도 사용할 수 있습니다.

관리 화면 실행:

```sh
.venv/bin/python admission_cli.py --admin
```

또는 `./admission-admin --admin`으로 실행합니다.

관리 모드에서는 Supabase Dashboard → Settings → API Keys의 **Secret key**를
터미널의 숨김 입력창에 붙여넣습니다. 기존 `service_role` 키도 지원합니다.
키를 HTML, `supabase-config.js`, GitHub 또는 채팅에 붙여넣지 않습니다.
입력한 키는 파일에 저장하지 않습니다. 로컬 비밀 관리 도구를 사용한다면
`SUPABASE_ADMIN_KEY` 환경변수로도 제공할 수 있습니다.

화면 사용법:

- 검색창에 부분 문자열 입력: 대소문자 구분 없이 이름·전화번호·이메일·바코드 검색.
- 상태 필터: 전체 / 입장 완료 / 미입장 / DB 미등록.
- `Ctrl+R` 또는 새로고침: Supabase 최신 상태를 다시 조회.
- 표의 행 선택 후 **선택 미입장 처리**: 해당 등록자만 되돌림 (`RESET` 확인).
- **전체 초기화** 또는 `Ctrl+X`: DB의 모든 행을 되돌림 (`RESET ALL` 확인).
  검색 결과만이 아니라 CSV에 없는 DB 행도 포함합니다.
- `/`: 검색창으로 이동. `Ctrl+Q`: 종료. 확인창에서 `Esc`: 취소.

현재 DB 스키마에서 미입장은 `status='pending'`, `checked_in_at=NULL`입니다.
`status` 자체는 NOT NULL 제약이 있으므로 NULL 대신 `pending`을 사용합니다.
전체 초기화는 한 번의 DB UPDATE로 처리하며 이름·전화번호·이메일·바코드는
변경하지 않습니다. 초기화 후 새로 입장 처리되는 사람은 다시 입장 완료로
표시됩니다. 웹 화면은 다음 자동 동기화 때 변경 상태를 읽습니다.

대화형 화면 대신 결과만 출력하거나 초기 검색어를 지정할 수도 있습니다:

```sh
.venv/bin/python admission_cli.py --search '@gmail.com'
.venv/bin/python admission_cli.py --list --search '0401'
```

관리 기능과 터미널 UI 테스트 (실제 DB 초기화 없음):

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_admission_cli.py' -v
```

If a registration exists in CSV but not DB, the app reports an error rather than
assuming the person is not yet admitted. Check configuration in
`supabase-config.js`, run the latest setup SQL, and import missing barcodes.
