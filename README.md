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

If a registration exists in CSV but not DB, the app reports an error rather than
assuming the person is not yet admitted. Check configuration in
`supabase-config.js`, run the latest setup SQL, and import missing barcodes.
