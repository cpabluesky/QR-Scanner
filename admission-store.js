/* Database access shared by scanning and name search. */
window.createAdmissionStore = function(client) {
  function fail(error) {
    if (error) throw new Error(error.message || '입장 DB 요청에 실패했습니다.');
  }

  return {
    async getStates(codes) {
      const unique = [...new Set(codes)];
      const states = new Map();
      for (let i = 0; i < unique.length; i += 100) {
        const {data, error} = await client.from('checkins')
          .select('bar_code,status,checked_in_at').in('bar_code', unique.slice(i, i + 100));
        fail(error);
        for (const row of data || []) {
          if (!['pending', 'checked_in'].includes(row.status) ||
              (row.status === 'checked_in' && !row.checked_in_at)) {
            throw new Error('입장 DB 상태가 올바르지 않습니다. 관리자에게 문의해 주세요.');
          }
          states.set(row.bar_code, row);
        }
      }
      if (unique.some(code => !states.has(code))) {
        throw new Error('입장 DB에 등록되지 않은 바코드가 있습니다. 명단을 DB에 가져왔는지 확인해 주세요.');
      }
      return states;
    },
    async checkIn(code) {
      const {data, error} = await client.rpc('check_in', {p_bar_code:code});
      fail(error);
      if (!data || data.success !== true || typeof data.found !== 'boolean' ||
          (data.found && (typeof data.alreadyCheckedIn !== 'boolean' || !data.checkInTime))) {
        throw new Error('입장 DB 응답을 확인할 수 없습니다. 다시 조회해 주세요.');
      }
      return data;
    }
  };
};
