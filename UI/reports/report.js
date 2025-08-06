const userInfoStr = localStorage.getItem('user_info');
let userInfo = null;
if (userInfoStr) {
    try {
        userInfo = JSON.parse(userInfoStr);
        console.log('user_info:', userInfo);
    } catch (e) {
        console.error('user_info 파싱 오류:', e);
    }
} else {
    console.warn('user_info가 localStorage에 없습니다.');
}

document.addEventListener('DOMContentLoaded', async () => {
  const userId = userInfo.userid;

  try {
    // 백엔드 API 호출 (예: /api/reports?userid=USER_ID)
    const response = await fetch(`https://zylo-useu.onrender.com/report/list?userid=${userId}`);
    if (!response.ok) throw new Error('서버 응답 오류');

    const reports = await response.json(); // [{date: '7월 3일'}, ...] 형태라고 가정
    console.log('리포트 데이터:', reports);

    // 대화 개수 표시
    const streakWeek = document.querySelector('.streak-week');
    if (streakWeek) {
      streakWeek.textContent = `${reports.length}번`;
    }

    const detailList = document.querySelector('.detail-list');
    detailList.innerHTML = ''; // 기존 내용 비우기
    // 리포트 개수 0일 때
    if (reports.length === 0) {
      detailList.innerHTML = '<p>아직 대화 내역이 없습니다</p>';
      return;
    }

    reports.forEach(report => {
      const dateObj = new Date(report.Date || report.date);
      const month = dateObj.getMonth() + 1;
      const day = dateObj.getDate();
      send_date = `${month}월 ${day}일`;
      const label = `${month}월 ${day}일 전화`;

      const a = document.createElement('a');
      a.href = `detailreport.html?reportid=${encodeURIComponent(report._id)}&date=${encodeURIComponent(send_date)}`;
      a.className = 'detail-item';
      a.innerHTML = `
        ${label}
        <span class="detail-arrow">&gt;</span>
      `;
      detailList.appendChild(a);
    });
  } catch (err) {
    console.error('리포트 불러오기 실패:', err);
  }
});