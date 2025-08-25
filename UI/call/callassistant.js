// 타이머 구현
let timer = 420; // 7분 = 420초
const timerElem = document.getElementById('callTimer');
let timerInterval = null;

// 타이머 함수
function updateTimer() {
  const min = String(Math.floor(timer / 60)).padStart(2, '0');
  const sec = String(timer % 60).padStart(2, '0');
  timerElem.textContent = `${min}:${sec}`;
  if (timer > 0) timer--;
  else clearInterval(timerInterval);
}

// 페이지 진입 시 타이머 시작
window.addEventListener('DOMContentLoaded', async () => {
  // ... 기존 마이크 권한 코드 ...
  updateTimer();
  timerInterval = setInterval(updateTimer, 1000);
});

let mediaStream = null; // 마이크 스트림을 저장할 변수
window.addEventListener('DOMContentLoaded', async () => {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    console.log('🎤 마이크 권한 미리 허용됨');
  } catch (err) {
    console.warn('마이크 권한 요청 거절됨', err);
  }
});

// user 정보 가져오기
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

// 가장 대화 ID 가져오기
// 서버에서 최신 대화 ID를 받아와서 conversationId 변수에 저장
let conversationId = null;
const agentTxt = document.getElementById('agentTxt');

async function fetchConversationId() {
  agentTxt.innerHTML =
    '이전 대화를 기반으로 연습 예제를 생성 중... <br>잠시만 기다려주세요.<br>약 30초 정도 소요됩니다.';
  if (!userInfo || !userInfo.userid) {
    console.error('userInfo가 없거나 userid가 없습니다.');
    return;
  }
  // URL 파라미터에서 reportId가 있는지 먼저 확인
  const params = new URLSearchParams(window.location.search);
  const reportIdParam = params.get('reportid');
  if (reportIdParam) {
    // detailreport에서 넘어온 경우: 파라미터로 받은 reportId 바로 사용
    window.conversationId = reportIdParam;
    console.log('파라미터로 받은 reportId:', reportIdParam);
  } else {
    // call에서 넘어온 경우: 서버에서 최신 대화 ID를 받아옴
    try {
      const res = await fetch(
        `https://zylo-useu.onrender.com/studymode/id?userid=${encodeURIComponent(
          userInfo.userid
        )}`
      );
      if (!res.ok) {
        throw new Error('서버에서 대화 ID를 받아오지 못했습니다.');
      }
      const data = await res.json();
      if (data.report_id) {
        console.log('data.report_id', data.report_id);
        window.conversationId = data.report_id;
      } else {
        console.warn('대화 내역이 없습니다.');
      }
    } catch (err) {
      console.error('대화 ID 요청 중 오류:', err);
    }
  }
}

async function fetchConversationIdAndConnectWS() {
  await fetchConversationId(); // 대화 ID를 먼저 받아옴
  if (window.conversationId) {
    // 대화 ID가 준비된 후에만 WebSocket 연결
    connectWebSocket(window.conversationId);
  } else {
    console.log('대화 ID가 없습니다. WebSocket 연결 안함.');
  }
}
function splitSentencesWithQuotes(text) {
  if (!text) return [];
  return text
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

function connectWebSocket(conversationId) {
  const ws = new WebSocket(
    `wss://zylo-useu.onrender.com/ws/audio/studymode?userid=${encodeURIComponent(
      userInfo.userid
    )}&username=${encodeURIComponent(
      userInfo.username
    )}&conversation_id=${encodeURIComponent(conversationId)}`
  );
  ws.binaryType = 'arraybuffer';

  ws.addEventListener('open', () => {
    console.log('WebSocket 연결됨');
  });
  ws.addEventListener('error', (e) => console.error('WS 에러', e));

  // 서버로부터 텍스트·PCM 청크 수신
  ws.addEventListener('message', async (ev) => {
    if (typeof ev.data === 'string') {
      const msg = JSON.parse(ev.data);

      if (msg.type === 'text') {
        console.log('msg', msg);
        lastEnSentences = splitSentencesWithQuotes(msg.answer);
        lastKoSentences = splitSentencesWithQuotes(msg.answer_kor);
        renderAgentTxt();
        console.log('user transcript:', msg.transcript);
      } else if (msg.type === 'DONE') {
        console.log('백엔드 전송 완료, 클라이언트 재생 대기중…');

        // 남은 재생 시간을 계산 (초 단위)
        const remainingSec = Math.max(0, nextTime - playCtx.currentTime);

        // 남은 시간 후에 버튼 복원
        setTimeout(() => {
          micBtn.disabled = false;
          micBtn.classList.remove('disabled');
          micBtn.classList.add('idle');
          micBtn.innerHTML = micSVG;
          nextTime = 0;
          if (timer === 0) {
            quitPopup();
          }
        }, remainingSec * 1000);
      }
      return;
    } else {
      // 음성 수신 ---------------------------------
      // 이진 PCM16 데이터
      const arrayBuffer = ev.data;
      const pcm16 = new Int16Array(arrayBuffer);
      // Float32로 변환
      const float32 = new Float32Array(pcm16.length);
      for (let i = 0; i < pcm16.length; i++) {
        float32[i] = pcm16[i] / 32768;
      }
      // 재생
      const buffer = playCtx.createBuffer(1, float32.length, SAMPLE_RATE);
      buffer.getChannelData(0).set(float32);
      const src = playCtx.createBufferSource();
      src.buffer = buffer;
      src.connect(playCtx.destination);
      if (nextTime === 0) {
        nextTime = playCtx.currentTime + 0.5;
      }
      src.start(nextTime);
      nextTime += buffer.duration;
    }
  });
  // 발신 -----------------------------------------------------
  micBtn.addEventListener('click', async () => {
    if (!isRecording) {
      // ▶️ 녹음 시작
      isRecording = true;
      micBtn.classList.remove('idle', 'disabled');
      micBtn.classList.add('recording');
      micBtn.innerHTML = waveSVG;
      // 타이머 시간 전송
      ws.send(
        JSON.stringify({
          type: 'timer',
          time: timerElem.textContent,
        })
      );
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      // user gesture 직후라도, 명시적으로 resume 해 줘야 onaudioprocess가 동작합니다
      if (audioCtx.state === 'suspended') {
        await audioCtx.resume();
        console.log('🟢 audioCtx resumed for recording');
      }
      if (!mediaStream) {
        mediaStream = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });
      }
      const source = audioCtx.createMediaStreamSource(mediaStream);
      recorderNode = audioCtx.createScriptProcessor(4096, 1, 1);
      source.connect(recorderNode);
      recorderNode.connect(audioCtx.destination);
      recorderNode.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);
        const down = downsampleBuffer(input, audioCtx.sampleRate, SAMPLE_RATE);
        const int16 = convertFloat32ToInt16(down);
        ws.send(int16.buffer);
      };
    } else {
      // ⏹️ 녹음 중지 + SEND 신호
      isRecording = false;
      micBtn.classList.remove('recording');
      micBtn.classList.add('disabled');
      micBtn.innerHTML = micSVG;
      micBtn.disabled = true;
      recorderNode.disconnect();
      audioCtx.close();
      ws.send('SEND');
    }
    if (playCtx.state === 'suspended') {
      await playCtx.resume();
      console.log('AudioContext resumed');
    }
  });

  // 종료 버튼
  endBtn.addEventListener('click', () => {
    if (isRecording) {
      recorderNode.disconnect();
      audioCtx.close();
      mediaStream.getTracks().forEach((t) => t.stop());
      micBtn.classList.remove('active');
      isRecording = false;
    }
    ws.close();
    window.location.href = '../main.html';
  });
}

window.addEventListener('DOMContentLoaded', fetchConversationIdAndConnectWS);

const micBtn = document.getElementById('micBtn');
const endBtn = document.getElementById('endBtn');

let audioCtx, recorderNode;
const SAMPLE_RATE = 24000; // 서버와 맞추기
let isRecording = false;

// 재생용 AudioContext
const playCtx = new (window.AudioContext || window.webkitAudioContext)({
  sampleRate: SAMPLE_RATE,
});

// 다운샘플링 함수 (48k → 16k 등)
function downsampleBuffer(buffer, srcRate, dstRate) {
  const sampleRateRatio = srcRate / dstRate;
  const newLength = Math.round(buffer.length / sampleRateRatio);
  const result = new Float32Array(newLength);
  let offsetResult = 0,
    offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
    let accum = 0,
      count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = accum / count;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

// Float32 → Int16
function convertFloat32ToInt16(buffer) {
  const l = buffer.length;
  const result = new Int16Array(l);
  for (let i = 0; i < l; i++) {
    let s = Math.max(-1, Math.min(1, buffer[i]));
    result[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return result;
}

function quitPopup() {
  const popup = document.getElementById('quitPopup');
  if (popup) {
    popup.style.display = 'flex';
    // 버튼 이벤트 등록
    const continueBtn = document.getElementById('continueStudyBtn');
    const switchBtn = document.getElementById('switchToCallBtn');
    const endBtn = document.getElementById('endCallBtn');

    if (continueBtn) {
      continueBtn.onclick = () => {
        popup.style.display = 'none';
        timer = 600;
      };
    }
    if (switchBtn) {
      switchBtn.onclick = () => {
        window.location.href = './call.html';
      };
    }
    if (endBtn) {
      endBtn.onclick = () => {
        window.location.href = '../main.html';
      };
    }
  }
}

// 수신 ------------------------------------------------------------------
let lastEnSentences = [];
let lastKoSentences = [];

// agentTxt 렌더링 함수
function renderAgentTxt() {
  let merged = [];
  const onlyEn = subtitleState.en && !subtitleState.ko;
  for (
    let i = 0;
    i < Math.max(lastEnSentences.length, lastKoSentences.length);
    i++
  ) {
    if (subtitleState.en && lastEnSentences[i]) {
      if (onlyEn) {
        merged.push(
          `<p class="agent-en" style="margin:0 0 10px 0;">${lastEnSentences[
            i
          ].trim()}</p>`
        );
      } else {
        merged.push(`<p class="agent-en">${lastEnSentences[i].trim()}</p>`);
      }
    }
    if (subtitleState.ko && lastKoSentences[i]) {
      merged.push(`<p class="agent-ko">${lastKoSentences[i].trim()}</p>`);
    }
  }
  agentTxt.innerHTML = merged.join('');
}

let nextTime = 0;

// 파형(waveform) 아이콘 SVG
const waveSVG = `
<svg viewBox="0 0 24 24" fill="none">
    <polyline points="1 12 5 12 5 6 9 18 9 12 13 12 13 8 17 16 17 12 21 12"/>
</svg>`;

// 기본 마이크 icon SVG (흰색)
const micSVG = `
<svg viewBox="0 0 24 24" fill="none">
    <rect x="9" y="2" width="6" height="12" rx="3"/>
    <path d="M5 10v2a7 7 0 0 0 14 0v-2"/>
    <line x1="12" y1="22" x2="12" y2="18"/>
    <line x1="8" y1="22" x2="16" y2="22"/>
</svg>`;

const subBtn = document.querySelector('.sub-btn');
const subtitlePopup = document.getElementById('subtitlePopup');
const closeSubtitlePopup = document.getElementById('closeSubtitlePopup');
const toggleEn = document.getElementById('toggleEn');
const toggleKo = document.getElementById('toggleKo');

// 자막 상태 저장 (기본 OFF)
let subtitleState = {
  en: true,
  ko: true,
};

// 팝업 열기
subBtn.addEventListener('click', () => {
  subtitlePopup.style.display = 'flex';
  // 현재 상태 반영
  toggleEn.classList.toggle('on', subtitleState.en);
  toggleEn.textContent = subtitleState.en ? 'ON' : 'OFF';
  toggleKo.classList.toggle('on', subtitleState.ko);
  toggleKo.textContent = subtitleState.ko ? 'ON' : 'OFF';
});

// 팝업 닫기
closeSubtitlePopup.addEventListener('click', () => {
  subtitlePopup.style.display = 'none';
});

// 영어 자막 토글
toggleEn.addEventListener('click', () => {
  subtitleState.en = !subtitleState.en;
  toggleEn.classList.toggle('on', subtitleState.en);
  toggleEn.textContent = subtitleState.en ? 'ON' : 'OFF';
  renderAgentTxt();
});

// 한글 자막 토글
toggleKo.addEventListener('click', () => {
  subtitleState.ko = !subtitleState.ko;
  toggleKo.classList.toggle('on', subtitleState.ko);
  toggleKo.textContent = subtitleState.ko ? 'ON' : 'OFF';
  renderAgentTxt();
});
