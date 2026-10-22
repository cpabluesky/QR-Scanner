// Runs against the actual store and inline app script (provided by run_tests.py).
const tests = [];
function test(name, run) { tests.push({name, run}); }
function assert(value, message = 'Assertion failed') { if (!value) throw new Error(message); }
async function rejects(work, message) {
  try { await work(); } catch (error) {
    assert(error.message.includes(message), error.message);
    return;
  }
  throw new Error('Expected rejection');
}
function fakeClient() {
  const state = {
    rows:[], reads:[], rpcCalls:[], error:null,
    rpcResult:{success:true,found:true,alreadyCheckedIn:false,checkInTime:'2026-10-22T11:00:00Z'}
  };
  const client = {
    get auth() { throw new Error('Public access must not call Auth'); },
    from(table) {
      return {select() { return {
        async in(column, codes) {
          assert(table === 'checkins' && column === 'bar_code');
          state.reads.push(codes);
          return {data:state.rows.filter(row => codes.includes(row.bar_code)),error:state.error};
        }
      }; }};
    },
    async rpc(name, args) {
      state.rpcCalls.push({name,args});
      return {data:state.rpcResult,error:state.error};
    }
  };
  return {state,client,store:window.createAdmissionStore(client)};
}

test('Public visitors can read and check in without calling Auth', async () => {
  const {state,store} = fakeClient();
  state.rows = [{bar_code:'3PINXMIKmdWm',status:'pending',checked_in_at:null}];
  assert((await store.getStates(['3PINXMIKmdWm'])).size === 1);
  assert((await store.checkIn('3PINXMIKmdWm')).success);
  assert(state.reads.length === 1 && state.rpcCalls.length === 1);
});
test('Exact-case barcode reads authoritative admission state', async () => {
  const {state,store} = fakeClient();
  state.rows = [{bar_code:'3PINXMIKmdWm',status:'checked_in',checked_in_at:'2026-10-22T11:00:00Z'}];
  const states = await store.getStates(['3PINXMIKmdWm']);
  assert(states.get('3PINXMIKmdWm').status === 'checked_in');
  await rejects(() => store.getStates(['3PINXMIKMDWM']), '등록되지 않은');
});
test('Missing DB records and network errors never become pending admissions', async () => {
  const {state,store} = fakeClient();
  await rejects(() => store.getStates(['missing']), '등록되지 않은');
  state.error = {message:'Network unavailable'};
  await rejects(() => store.getStates(['missing']), 'Network unavailable');
  await rejects(() => store.checkIn('missing'), 'Network unavailable');
});
test('Large name result sets use bounded batches', async () => {
  const {state,store} = fakeClient();
  state.rows = Array.from({length:205}, (_,i) => ({bar_code:String(i),status:'pending',checked_in_at:null}));
  const states = await store.getStates(state.rows.map(row => row.bar_code));
  assert(states.size === 205 && state.reads.length === 3);
  assert(state.reads.every(codes => codes.length <= 100));
});
test('RPC preserves exact barcode and duplicate admission response', async () => {
  const {state,store} = fakeClient();
  const first = await store.checkIn('3PINXMIKmdWm');
  state.rpcResult = {...first,alreadyCheckedIn:true};
  const second = await store.checkIn('3PINXMIKmdWm');
  assert(state.rpcCalls[0].name === 'check_in');
  assert(state.rpcCalls[0].args.p_bar_code === '3PINXMIKmdWm');
  assert(second.alreadyCheckedIn && first.checkInTime === second.checkInTime);
  state.rpcResult = null;
  await rejects(() => store.checkIn('code'), '응답');
});
test('Malformed admission data is rejected', async () => {
  const {state,store} = fakeClient();
  state.rows = [{bar_code:'code',status:'checked_in',checked_in_at:null}];
  await rejects(() => store.getStates(['code']), '올바르지');
});
test('Actual page looks up the reported barcode, merges DB state and fails closed', async () => {
  const {store,state} = fakeClient();
  state.rows = [{bar_code:'3PINXMIKmdWm',status:'checked_in',checked_in_at:'2026-10-22T11:00:00Z'}];
  const elements = new Map();
  const document = {getElementById(id) {
    if (!elements.has(id)) elements.set(id,{style:{},textContent:'',hidden:false});
    return elements.get(id);
  }};
  const runPage = new Function('window','document','Html5Qrcode','fetch',
    'store','testCSV','assert', PAGE_SCRIPT + `
      return (async () => {
        await loadRegistrations();
        admissionStore = store; admissionsConfigured = true;
        const lookup = code => new Promise(resolve => localLookup(code, resolve));
        const person = await lookup('3PINXMIKmdWm');
        assert(person.success && person.found && person.alreadyCheckedIn);
        assert(person.code === '3PINXMIKmdWm' && person.checkInTime.includes('22'));
        const result = await new Promise(resolve => localSearch(person.name, resolve));
        assert(result.success && result.results.some(p => p.code === person.code && p.alreadyCheckedIn));
        assert(!(await lookup('3PINXMIKMDWM')).found);
        store.getStates = async () => { throw new Error('Network unavailable'); };
        const denied = await lookup('3PINXMIKmdWm');
        assert(!denied.success);
      })();`);
  await runPage({},document,function(){},async () => ({ok:true,text:async () => TEST_CSV}),
    store,TEST_CSV,assert);
});

test('Visible cards sync other-device admission, recover from errors and discard stale refreshes', async () => {
  const {store,state} = fakeClient();
  state.rows = [{bar_code:'3PINXMIKmdWm',status:'pending',checked_in_at:null}];
  const elements = new Map();
  const document = {
    hidden:false,
    getElementById(id) {
      if (!elements.has(id)) elements.set(id,{style:{},textContent:'',hidden:false});
      return elements.get(id);
    },
    createElement() {
      return {textContent:'',get innerHTML() { return this.textContent; }};
    }
  };
  const runPage = new Function('window','document','Html5Qrcode','fetch',
    'store','state','assert', PAGE_SCRIPT + `
      return (async () => {
        await loadRegistrations();
        admissionStore = store; admissionsConfigured = true;
        currentQRCode = '3PINXMIKmdWm';
        const person = registrationByCode.get(currentQRCode);
        displayPerson(combinedPerson(person,state.rows[0]));
        assert(document.getElementById('checkInButton').style.display === 'block');
        state.rows[0] = {...state.rows[0],status:'checked_in',checked_in_at:'2026-10-22T11:00:00Z'};
        await refreshVisibleAdmissions();
        assert(document.getElementById('checkInButton').style.display === 'none');
        assert(document.getElementById('checkInStatus').innerHTML.includes('이미 입장'));
        state.error = {message:'Network unavailable'};
        await refreshVisibleAdmissions();
        assert(document.getElementById('databaseMessage').textContent.includes('동기화하지 못했습니다'));
        assert(document.getElementById('checkInButton').disabled);
        state.error = null;
        await refreshVisibleAdmissions();
        assert(document.getElementById('databaseMessage').textContent.includes('동기화됨'));
        const reads = state.reads.length;
        document.hidden = true;
        await refreshVisibleAdmissions();
        assert(state.reads.length === reads);
        document.hidden = false;
        checkInPending = true;
        await refreshVisibleAdmissions();
        assert(state.reads.length === reads);
        checkInPending = false;
        let resolve;
        store.getStates = () => new Promise(done => { resolve = done; });
        const refresh = refreshVisibleAdmissions();
        admissionViewVersion++;
        document.getElementById('personCard').style.display = 'none';
        resolve(new Map([[person.code,state.rows[0]]]));
        await refresh;
        assert(document.getElementById('personCard').style.display === 'none');
      })();`);
  await runPage({},document,function(){},async () => ({ok:true,text:async () => TEST_CSV}),
    store,state,assert);
});

test('Statistics use all registered barcodes and search matches name, phone and email fragments', async () => {
  const {store,state} = fakeClient();
  const elements = new Map();
  const document = {hidden:false,getElementById(id) {
    if (!elements.has(id)) elements.set(id,{style:{},textContent:'',hidden:false});
    return elements.get(id);
  }};
  const runPage = new Function('window','document','Html5Qrcode','fetch',
    'store','state','assert', PAGE_SCRIPT + `
      return (async () => {
        await loadRegistrations();
        admissionStore = store; admissionsConfigured = true;
        assert(registrationList.length === 401);
        state.rows = registrationList.map((p,i) => ({bar_code:p.code,
          status:i < 100 ? 'checked_in' : 'pending',
          checked_in_at:i < 100 ? '2026-10-22T11:00:00Z' : null}));
        await refreshAdmissionStatistics();
        assert(document.getElementById('admissionStatsCount').textContent === '100명 / 401명 입장');
        assert(document.getElementById('admissionStatsPercentage').textContent === '입장률 24.9%');
        assert(Math.abs(document.getElementById('admissionProgress').value - 100/401*100) < 0.001);
        state.error = {message:'Network unavailable'};
        await refreshAdmissionStatistics();
        assert(document.getElementById('admissionStatsMessage').textContent.includes('확인하지 못했습니다'));
        assert(document.getElementById('admissionStatsCount').textContent === '100명 / 401명 입장');
        state.error = null;
        for (const row of state.rows) { row.status = 'pending'; row.checked_in_at = null; }
        await refreshAdmissionStatistics();
        assert(document.getElementById('admissionStatsPercentage').textContent === '입장률 0.0%');
        for (const row of state.rows) { row.status = 'checked_in'; row.checked_in_at = '2026-10-22T11:00:00Z'; }
        await refreshAdmissionStatistics();
        assert(document.getElementById('admissionStatsPercentage').textContent === '입장률 100.0%');
        document.getElementById('admissionStatistics').hidden = true;
        const reads = state.reads.length;
        await refreshAdmissionStatistics();
        assert(state.reads.length === reads);
        registrationList = [
          {code:'A',name:'Alice',phone:'0401 239 857',email:'first@example.com'},
          {code:'B',name:'Bob',phone:'0499000000',email:'alice@OTHER.org'},
          {code:'C',name:'승현',phone:'0411-222-333',email:'other@example.net'}
        ];
        state.rows = registrationList.map(p => ({bar_code:p.code,status:'pending',checked_in_at:null}));
        const search = q => new Promise(resolve => localSearch(q,resolve));
        assert((await search('ALICE')).results.map(p=>p.code).join(',') === 'A,B');
        assert((await search('401239')).results[0].code === 'A');
        assert((await search('0411222')).results[0].code === 'C');
        assert((await search('@other.ORG')).results[0].code === 'B');
        assert((await search('승')).results[0].code === 'C');
        assert(!(await search('   ')).found);
        assert(!(await search('no matching person')).found);
      })();`);
  await runPage({},document,function(){},async () => ({ok:true,text:async () => TEST_CSV}),
    store,state,assert);
});

globalThis.testResult = null;
(async () => {
  const passed = [];
  for (const {name,run} of tests) { await run(); passed.push(name); }
  return passed;
})().then(passed => { globalThis.testResult = {passed}; },
  error => { globalThis.testResult = {error:error.message,stack:error.stack}; });
