from fastapi import FastAPI, WebSocket, Request
from google import genai
from openai import AsyncOpenAI
from datetime import datetime
import os
import io, wave
from call import (
    start_conversation,
    stt,
    generate_llm_response,
    start_conversation_study,
    generate_llm_response_study,
)
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from bson import ObjectId
import json
from generate_vector_DB import GenerateVectorDB

MONGO_URI = os.getenv("MONGO_URI")  # 환경에 맞게 수정
client = MongoClient(MONGO_URI)
db = client["Zylo"]  # 사용할 DB 이름
users_collection = db["users"]  # 회원 정보 저장할 컬렉션
conversations_collection = db["conversations"]  # 대화 기록 저장할 컬렉션
vector_db = GenerateVectorDB(
    openai_api_key=os.getenv("OPENAI_API_KEY"), cache_dir="cache"
)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

gm_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
oa_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# 회원가입
@app.post("/signup")
async def signup(request: Request):
    data = await request.json()
    if users_collection.find_one({"userid": data["userid"]}):
        return JSONResponse(
            content={"message": "이미 존재하는 사용자입니다."}, status_code=400
        )
    users_collection.insert_one(data)
    # print(data)
    user_info = {
        "userid": data.get("userid", ""),
        "username": data.get("username", ""),
        "interest": data.get("interest", ""),
    }
    return JSONResponse(content={"message": "회원가입 성공", "user": user_info})


# 로그인
@app.post("/login")
async def login(request: Request):
    data = await request.json()
    user = users_collection.find_one({"userid": data["userid"]})
    if user:
        return JSONResponse(
            content={
                "message": "로그인 성공",
                "user": {
                    "userid": user["userid"],
                    "username": user.get("username", ""),
                    "interest": user.get("interest", ""),
                },
            }
        )
    return JSONResponse(
        content={"message": "존재하지 않는 사용자입니다."}, status_code=400
    )


# 대화 내역 조회
@app.get("/report/list")
async def get_report_list(request: Request):
    user_id = request.query_params.get("userid")
    if not user_id:
        return JSONResponse(
            content={"message": "사용자 정보가 없습니다."}, status_code=400
        )

    reports_cursor = conversations_collection.find({"userid": user_id})
    reports = []
    for doc in reports_cursor:
        doc["_id"] = str(doc["_id"])  # ObjectId → 문자열로 변환
        if isinstance(doc.get("Date"), datetime):
            doc["Date"] = doc["Date"].isoformat()
        reports.append(doc)

    return JSONResponse(content=reports)


# 세부 대화 기록 조회
@app.get("/report/detail")
async def get_report_detail(request: Request):
    user_id = request.query_params.get("userid")
    report_id = request.query_params.get("reportid")
    if not user_id or not report_id:
        return JSONResponse(
            content={"message": "사용자 정보가 없습니다."}, status_code=400
        )

    try:
        obj_id = ObjectId(report_id)
    except Exception:
        return JSONResponse(
            content={"message": "잘못된 reportid 형식입니다."}, status_code=400
        )

    report = conversations_collection.find_one({"userid": user_id, "_id": obj_id})
    if not report:
        return JSONResponse(
            content={"message": "존재하지 않는 보고서입니다."}, status_code=404
        )

    report["_id"] = str(report["_id"])  # ObjectId → 문자열로 변환
    if isinstance(report.get("Date"), datetime):
        report["Date"] = report["Date"].isoformat()

    return JSONResponse(content=report)


def make_wav_bytes(pcm_bytes, sample_rate=24000, channels=1, sampwidth=2):
    """raw PCM16LE bytes → WAV 파일 bytes"""
    buf = io.BytesIO()
    wf = wave.open(buf, "wb")
    wf.setnchannels(channels)
    wf.setsampwidth(sampwidth)  # 2 bytes for int16
    wf.setframerate(sample_rate)
    wf.writeframes(pcm_bytes)
    wf.close()
    return buf.getvalue()


@app.websocket("/ws/audio")
async def audio_ws(ws: WebSocket):
    user_id = ws.query_params.get("userid")
    user_name = ws.query_params.get("username")
    user_interest = ws.query_params.get("interest")
    # print(f"user_id: {user_id}, user_name: {user_name}, user_interest: {user_interest}")
    await ws.accept()
    audio_buffer = io.BytesIO()
    conversation_history = []
    timer_value = None

    response = start_conversation(user_id, user_name, user_interest)
    res = response.parsed
    answer = res["answer"]
    answer_kor = res["answer_kor"]
    conversation_history.append(
        {
            "role": "model",
            "parts": [{"text": answer}],
        }
    )

    await ws.send_json({"type": "text", "answer": answer, "answer_kor": answer_kor})

    # TTS 스트리밍
    async with oa_client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice="coral",
        input=answer,
        instructions="Speak in a natural tone.",
        response_format="pcm",
    ) as stream:
        async for chunk in stream.iter_bytes(chunk_size=1024):
            await ws.send_bytes(chunk)
    await ws.send_json({"type": "DONE"})

    while True:
        # 1) 오디오 스트림 수신
        msg = await ws.receive()

        if msg["type"] == "websocket.receive" and msg.get("bytes") is not None:
            audio_buffer.write(msg["bytes"])
            continue
        if msg["type"] == "websocket.receive" and msg.get("text"):
            text = msg["text"]
            try:
                data = json.loads(text)
                if data.get("type") == "timer":
                    timer_value = data.get("time")
                    # print(f"타이머 값 수신: {timer_value}")
                    continue  # 타이머 값만 받고 다음 루프
            except Exception:
                pass
            if text == "SEND":
                full_audio_bytes = audio_buffer.getvalue()
                wav_bytes = make_wav_bytes(full_audio_bytes)

                # with open("output.wav", "wb") as f:
                #     f.write(wav_bytes)

            # 2) stt
            transcript = stt(wav_bytes)
            # 3) llm 응답 생성
            response = generate_llm_response(transcript, user_id, conversation_history)
            answer = response["response"]
            answer_kor = response["korean_translation"]

            conversation_history.append(
                {
                    "role": "user",
                    "parts": [{"text": transcript}],
                }
            )
            conversation_history.append(
                {
                    "role": "model",
                    "parts": [{"text": answer}],
                }
            )

            # 4-1) 텍스트 응답 먼저 전송
            await ws.send_json(
                {
                    "type": "text",
                    "transcript": transcript,
                    "answer": answer,
                    "answer_kor": answer_kor,
                }
            )
            # print(
            #     f"transcript: {transcript}, answer: {answer}, answer_kor: {answer_kor}"
            # )
            # 4-2) TTS 스트리밍
            async with oa_client.audio.speech.with_streaming_response.create(
                model="gpt-4o-mini-tts",
                voice="coral",
                input=answer,
                instructions="Speak in a natural tone.",
                response_format="pcm",
            ) as stream:
                async for chunk in stream.iter_bytes(chunk_size=1024):
                    await ws.send_bytes(chunk)
            await ws.send_json({"type": "DONE"})

            # 4) 다음 입력 위해서 버퍼 초기화
            audio_buffer = io.BytesIO()
            continue

        # 5) 클라이언트 연결 종료
        if msg["type"] == "websocket.disconnect":
            user = users_collection.find_one({"userid": user_id})
            conversations_collection.insert_one(
                {
                    "userid": user_id,
                    "Date": datetime.now(),
                    "conversation": conversation_history,
                }
            )
            print(conversation_history)
            print("DB 저장완료")
            # RAG 저장
            conversation_id = vector_db.save_full_conversation(
                user_id=user_id,
                conversation_history=conversation_history,
                date=datetime.now().isoformat(),
            )
            print("Vector DB 저장완료")
            print("WebSocket disconnected")
            break


# 공부 모드 ------------------------------------------------------------------------------
# 대화 내역 조회
@app.get("/studymode/id")
async def get_conversation_id(request: Request):
    user_id = request.query_params.get("userid")
    if not user_id:
        return JSONResponse(
            content={"message": "사용자 정보가 없습니다."}, status_code=400
        )

    latest_report = (
        conversations_collection.find({"userid": user_id}).sort("Date", -1).limit(1)
    )
    latest_report = list(latest_report)
    if latest_report:
        report_id = str(latest_report[0]["_id"])
        return JSONResponse(content={"report_id": report_id})
    else:
        return JSONResponse(
            content={"message": "대화 내역이 없습니다."}, status_code=404
        )


@app.websocket("/ws/audio/studymode")
async def audio_ws(ws: WebSocket):
    user_id = ws.query_params.get("userid")
    user_name = ws.query_params.get("username")
    conversation_id = ws.query_params.get("conversation_id")
    # print(f"user_id: {user_id}, user_name: {user_name}")
    await ws.accept()
    audio_buffer = io.BytesIO()
    conversation_history = []
    timer_value = None

    await ws.send_json(
        {
            "type": "wait",
            "message": "이전 대화 내용을 분석하고 있어요. 잠시만 기다려주세요...",
        }
    )

    response = start_conversation_study(user_id, user_name, conversation_id)
    # print(response)
    answer = response["answer"]
    answer_kor = response["answer_kor"]
    recommended_phrases = response["recommended_phrases"]
    conversation_history.append(
        {
            "role": "model",
            "parts": [{"text": answer}],
        }
    )

    await ws.send_json({"type": "text", "answer": answer, "answer_kor": answer_kor})

    # TTS 스트리밍
    async with oa_client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice="coral",
        input=answer,
        instructions="Speak in a natural tone.",
        response_format="pcm",
    ) as stream:
        async for chunk in stream.iter_bytes(chunk_size=1024):
            await ws.send_bytes(chunk)
    await ws.send_json({"type": "DONE"})

    while True:
        # 1) 오디오 스트림 수신
        msg = await ws.receive()

        if msg["type"] == "websocket.receive" and msg.get("bytes") is not None:
            audio_buffer.write(msg["bytes"])
            continue
        if msg["type"] == "websocket.receive" and msg.get("text"):
            text = msg["text"]
            try:
                data = json.loads(text)
                if data.get("type") == "timer":
                    timer_value = data.get("time")
                    # print(f"타이머 값 수신: {timer_value}")
                    continue  # 타이머 값만 받고 다음 루프
            except Exception:
                pass
            if text == "SEND":
                full_audio_bytes = audio_buffer.getvalue()
                wav_bytes = make_wav_bytes(full_audio_bytes)

                # with open("output.wav", "wb") as f:
                #     f.write(wav_bytes)

            # 2) stt
            # transcript = stt(wav_bytes)
            # 3) llm 응답 생성
            response = generate_llm_response_study(
                wav_bytes, conversation_history, recommended_phrases
            )
            transcript = response["transcript"]
            answer = response["response"]
            answer_kor = response["korean_translation"]
            # print(f"answer: {answer}, answer_kor: {answer_kor}")

            conversation_history.append(
                {
                    "role": "user",
                    "parts": [{"text": transcript}],
                }
            )
            conversation_history.append(
                {
                    "role": "model",
                    "parts": [{"text": answer}],
                }
            )

            # 4-1) 텍스트 응답 먼저 전송
            await ws.send_json(
                {
                    "type": "text",
                    "transcript": transcript,
                    "answer": answer,
                    "answer_kor": answer_kor,
                }
            )

            # 4-2) TTS 스트리밍
            async with oa_client.audio.speech.with_streaming_response.create(
                model="gpt-4o-mini-tts",
                voice="coral",
                input=answer,
                instructions="Speak in a natural tone.",
                response_format="pcm",
            ) as stream:
                async for chunk in stream.iter_bytes(chunk_size=1024):
                    await ws.send_bytes(chunk)
            await ws.send_json({"type": "DONE"})

            # 4) 다음 입력 위해서 버퍼 초기화
            audio_buffer = io.BytesIO()
            continue

        # 5) 클라이언트 연결 종료
        if msg["type"] == "websocket.disconnect":
            print(conversation_history)
            print("WebSocket disconnected")
            break
