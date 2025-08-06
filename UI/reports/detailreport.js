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

const params = new URLSearchParams(window.location.search);
const reportId = params.get('reportid');
const date = params.get('date');
console.log(date ? `받아온 날짜: ${date}` : '날짜 정보가 없습니다.');

document.addEventListener('DOMContentLoaded', async () => {
  const userId = userInfo.userid;
  const chatTitle = document.querySelector('.chat-title');
  if (chatTitle && date) {
    chatTitle.textContent = `상세 대화 내용 기록 (${date})`;
  }

  try {
    // 백엔드 API 호출 (예: /api/reports/detail?reportid=REPORT_ID)
    const response = await fetch(
      `https://zylo-useu.onrender.com/report/detail?userid=${userId}&reportid=${encodeURIComponent(
        reportId
      )}`
    );
    if (!response.ok) throw new Error('서버 응답 오류');

    const reportDetail = await response.json(); // 상세 리포트 데이터
    console.log('리포트 상세 데이터:', reportDetail);

    // 페이지에 리포트 내용 표시
    const detailContainer = document.querySelector('.chat-list-scroll-area');
    if (reportDetail.conversation && Array.isArray(reportDetail.conversation)) {
      let html = '';
      for (let i = 0; i < reportDetail.conversation.length; i += 2) {
        // 각 항목이 object 형태로 저장되어 있으므로 text만 추출
        const zyloObj = reportDetail.conversation[i] || {};
        const userObj = reportDetail.conversation[i + 1] || {};

        // "role"이 "model"이면 ZYLO, "user"면 사용자 + 텍스트 정제까지 한 번에 처리
        const removeBracketsAndTime = (text) => {
          if (!text) return '';
          // []로 된 부분 제거
          let result = text.replace(/\[[^\]]*\]/g, '');
          // 00:00 또는 00:00:00 등 시간 패턴 제거 (띄어쓰기 포함)
          result = result.replace(/\b\d{2}:\d{2}(?::\d{2})?\b/g, '');
          // 여러 개의 공백을 하나로 줄이고 양쪽 공백 제거
          return result.replace(/\s+/g, ' ').trim();
        };

        const zyloMsg = removeBracketsAndTime(
          zyloObj.role === 'model' &&
            zyloObj.parts &&
            zyloObj.parts[0] &&
            zyloObj.parts[0].text
            ? zyloObj.parts[0].text
            : ''
        );
        const userMsg = removeBracketsAndTime(
          userObj.role === 'user' &&
            userObj.parts &&
            userObj.parts[0] &&
            userObj.parts[0].text
            ? userObj.parts[0].text
            : ''
        );
        html += `
            <div class="chat-block">
                <div class="chat-meta">ZYLO</div>
                <div class="chat-system-msg">${zyloMsg}</div>
                <div class="chat-user-msg">${userMsg}</div>
            </div>
            `;
      }
      detailContainer.innerHTML = html;
    } else {
      detailContainer.innerHTML = '<p>대화 내역이 없습니다.</p>';
    }
  } catch (err) {
    console.error('리포트 상세 불러오기 실패:', err);
    const detailContainer = document.querySelector('.chat-list-scroll-area');
    detailContainer.innerHTML =
      '<p>리포트 상세 정보를 불러오는 데 실패했습니다.</p>';
  }

  // 공부모드 버튼 이벤트 리스너 추가
  const studyBtn = document.getElementById('study-mode-btn');
  if (studyBtn) {
    studyBtn.addEventListener('click', () => {
      window.location.href = `../call/callassistant.html?reportid=${encodeURIComponent(
        reportId
      )}`;
    });
  }
});
