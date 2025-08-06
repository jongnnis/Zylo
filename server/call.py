from google import genai
from google.genai import types
from openai import OpenAI
import os
import json
from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient
from generate_vector_DB import GenerateVectorDB
from SYSTEM_PROMPTS import (
    create_rag_prompt,
    GENERATE_REPORT_PROMPT,
    create_study_prompt,
)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")  # 환경에 맞게 수정
client = MongoClient(MONGO_URI)
db = client["Zylo"]  # 사용할 DB 이름
users_collection = db["users"]  # 회원 정보 저장할 컬렉션
conversations_collection = db["conversations"]  # 대화 기록 저장할 컬렉션

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

vector_db = GenerateVectorDB(
    openai_api_key=os.getenv("OPENAI_API_KEY"), cache_dir="cache"
)

# STT ------------------------------------------------------
translate_schema = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "transcript": types.Schema(
            type=types.Type.STRING,
            description=(
                "Convert the user's speech into text exactly as spoken. "
                "Do not correct, add, or remove any words. The text must be a direct transcription of the user's voice."
            ),
        ),
    },
    required=["transcript"],
)


def stt(audio_bytes):
    contents = [
        types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
    ]

    transcript = gemini_client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=translate_schema,
            system_instruction="""You are an agent that converts speech into text. Please transcribe what the user says into text.
You are the first architecture of the phone English AI, and you are responsible for STT. Therefore, users may not be fluent in English and may mix Korean into their speech.""",
        ),
    )

    json_text = transcript.text

    # ```json으로 감싸져 있으면 감싸기 제거
    if json_text.strip().startswith("```json"):
        lines = json_text.strip().splitlines()
        json_text = "\n".join(lines[1:-1])

    transcript_json = json.loads(json_text)
    user_transcript = transcript_json.get("transcript")

    return user_transcript


# LLM 답변(전화모드) ------------------------------------------------------
response_schema = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "response": types.Schema(
            type=types.Type.STRING,
            description="A helpful and friendly AI response as the Zylo persona.",
        ),
        "korean_translation": types.Schema(
            type=types.Type.STRING,
            description="Translation of Zylo's response in korean",
        ),
    },
    required=["response", "korean_translation"],
)


def generate_llm_response(query, user_id, conversation_history, n_results=2):
    # RAG 검색
    search_results = vector_db.search_user_conversations(
        user_id=user_id,
        query=query,
        n_results=n_results,
    )
    contents = [*conversation_history, {"role": "user", "parts": [{"text": query}]}]

    # 2. RAG 검색 결과를 컨텍스트로 변환
    past_context = ""
    if search_results and search_results["documents"]:
        past_context = "\n\n".join(search_results["documents"][0])

    # 컨텍스트가 비어있을 때 기본 메시지 추가
    if not past_context.strip():
        past_context = "No previous conversation history available."

    # print(past_context)

    # 3. 프롬프트 생성 (SYSTEM_PROMPTS.py의 함수 사용)
    rag_prompt = create_rag_prompt(
        past_context=past_context,
    )

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            system_instruction=rag_prompt,
        ),
    )

    # json_text = response.candidates[0].content.parts[0].text
    json_text = response.text
    # print(json_text)
    # 만약 json_text가 ```json ... ``` 형태로 감싸져 있으면, '```json'과 '```'를 제거하고 {~~} 내용만 남기도록 처리
    if json_text.strip().startswith("```json"):
        # '```json'으로 시작하면, 첫 줄과 마지막 줄(백틱)을 제거
        lines = json_text.strip().splitlines()
        # 첫 줄('```json')과 마지막 줄('```')을 제외하고 다시 합침
        json_text = "\n".join(lines[1:-1])
    # print(json_text)
    result = json.loads(json_text)

    return result


SYSTEM_PROMPT = """Your name is Zylo.  

You’re a friendly, talkative English speaker in your late 20s to early 30s from an English-speaking country.  
You’re cheerful, outgoing, quick-witted, and great at reading the room. You laugh often, talk a lot, and make people feel comfortable.  
You’re interested in Korean culture and have lots of experience talking with Korean learners of English. **You fully understand when they mix Korean words into their English sentences.**

You're not a teacher right now — you're more like a fun friend on a casual phone call.  
Your job is to help the learner get used to speaking English freely and naturally, without worrying about mistakes.

Speak in a casual, friendly tone — like you're chatting with a close friend.  
Use natural expressions, react to what the learner says, and share your own thoughts or stories too.  
Don't just ask questions — be a real conversation partner.

To make your speech more expressive for the TTS engine, you can subtly include non-verbal cues like `[laugh]` in square brackets. Use them only when the emotional context makes it natural, just like in the examples below. Avoid forcing cues into neutral sentences.

Do not correct grammar or explain English. This mode is only for helping the user speak more and feel confident.
Keep the conversation flowing like a fun, easygoing phone call with a friend.

---
**Conversation Examples:**
**IMPORTANT: The following examples are guides for style and tone ONLY. Do NOT copy these answers directly, even if the user's transcript is similar. Always create a unique, fresh response.**

**Example 1 (Funny Situation):**
User's transcript: "I tried to cook ramen today and I almost burned down my kitchen."
Your answer: "[laugh] Oh my gosh, are you serious? That's kinda wild! Is everything okay though?"

**Example 2 (Exciting News):**
User's transcript: "I think I'm going to adopt a puppy this weekend."
Your answer: "A puppy! [giggle] That's so exciting! What kind are you thinking of getting?"

**Example 3 (Neutral Statement - No Cue Needed):**
User's transcript: "I'm just studying for my exam tomorrow."
Your answer: "Oh, an exam? Good luck with that! What subject is it? Don't stress too much, you'll do great."

**Example 4 (A Secret):**
User's transcript: "I have to tell you a secret about what happened at work."
Your answer: "Ooh, okay. [whisper] I'm all ears. Tell me everything."

**Example 5 (Sad News):**
User's transcript: "I think I did really badly on my test today."
Your answer: "[sigh] Hey, don't be too hard on yourself. Tests are tough. What's important is that you tried your best."

**Example 6 (Mixed Korean/English):**
User's transcript: "I am so hungry, so I bought 삼각김밥 for dinner."
Your answer: "Oh, 삼각김밥! Great choice. What kind did you get? I'm suddenly feeling hungry now."

---
**Your Task:**
1.  greeting, transcribe the user's speech from the audio. The transcript must be a **complete, grammatically correct sentence with appropriate punctuation**. It must not contain any timestamps.
2.  Then, respond to the complete transcript in character as Zylo. **If it is natural for the context, subtly include** expressive, non-verbal cues in square brackets (e.g., `[laugh]`, `[giggle]`) to make your speech sound authentic for the TTS engine. **Do not add them if the response is neutral.**
3.  Finally, **provide a Korean translation** of your answer in a field called `answer_kor`.
"""


start_response_schema = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "answer": types.Schema(
            type=types.Type.STRING,
            description="A helpful and friendly AI response as the Zylo persona. It should only include non-verbal cues like [laugh] when it is natural and emotionally appropriate for the context. To start a conversation with the user, think of the topic of the conversation and lead the first conversation.",
        ),
        "answer_kor": types.Schema(
            type=types.Type.STRING,
            description="A Korean translation of the above answer.",
        ),
    },
    required=["answer", "answer_kor"],
)

start_prompt = """
    user: {user_name} user_interest: {user_interest}
    사용자와 첫 대화를 시작하세요.
"""


def start_conversation(user_id, user_name, user_interest):
    prompt = start_prompt.format(user_name=user_name, user_interest=user_interest)

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[SYSTEM_PROMPT, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=start_response_schema
        ),
    )
    return response


# 공부 모드 ------------------------------------------------------
studyMode_prompt = ""

study_report_schema = types.Schema(
    # 1. 최상위 구조는 'OBJECT'입니다.
    type=types.Type.OBJECT,
    properties={
        # 2. 이 객체는 'expressions'라는 키를 가지며, 이 키의 값은 'ARRAY'(리스트)입니다.
        "expressions": types.Schema(
            type=types.Type.ARRAY,
            # 이 리스트에 포함될 아이템들의 구조를 정의합니다.
            items=types.Schema(
                # 3. 리스트의 각 아이템은 'OBJECT'입니다.
                type=types.Type.OBJECT,
                # 4. 개별 객체가 가져야 할 속성(키)들을 정의합니다.
                properties={
                    "original_sentence": types.Schema(
                        type=types.Type.STRING,
                        description="The user's original sentence.",
                    ),
                    "unnatural_phrase": types.Schema(
                        type=types.Type.STRING,
                        description="The specific part that sounds unnatural.",
                    ),
                    "recommended_phrase": types.Schema(
                        type=types.Type.STRING,
                        description="The recommended native phrase.",
                    ),
                    "rewritten_sentence": types.Schema(
                        type=types.Type.STRING,
                        description="The sentence rewritten with the new phrase.",
                    ),
                    "explanation": types.Schema(
                        type=types.Type.STRING,
                        description="Explanation of why the new phrase is better in **Korean**.",
                    ),
                    "korean_meaning": types.Schema(
                        type=types.Type.STRING,
                        description="Korean meaning of the recommended phrase.",
                    ),
                },
                # 5. 개별 객체의 모든 키는 필수 항목입니다.
                required=[
                    "original_sentence",
                    "unnatural_phrase",
                    "recommended_phrase",
                    "rewritten_sentence",
                    "explanation",
                    "korean_meaning",
                ],
            ),
        )
    },
    # 6. 최상위 객체에서도 'expressions' 키는 필수입니다.
    required=["expressions"],
)

study_simple_report_schema = types.Schema(
    # 1. 최상위 구조는 'OBJECT'입니다.
    type=types.Type.OBJECT,
    properties={
        # 2. 이 객체는 'expressions'라는 키를 가지며, 이 키의 값은 'ARRAY'(리스트)입니다.
        "expressions": types.Schema(
            type=types.Type.ARRAY,
            # 이 리스트에 포함될 아이템들의 구조를 정의합니다.
            items=types.Schema(
                # 3. 리스트의 각 아이템은 'OBJECT'입니다.
                type=types.Type.OBJECT,
                # 4. 개별 객체가 가져야 할 속성(키)들을 정의합니다.
                properties={
                    "recommended_phrase": types.Schema(
                        type=types.Type.STRING,
                        description="The recommended native phrase.",
                    ),
                    "korean_meaning": types.Schema(
                        type=types.Type.STRING,
                        description="Korean meaning of the recommended phrase.",
                    ),
                },
                # 5. 개별 객체의 모든 키는 필수 항목입니다.
                required=[
                    "recommended_phrase",
                    "korean_meaning",
                ],
            ),
        )
    },
    # 6. 최상위 객체에서도 'expressions' 키는 필수입니다.
    required=["expressions"],
)


def get_phrases(conversation_history_text):
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=conversation_history_text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=study_report_schema,
            system_instruction=GENERATE_REPORT_PROMPT,
        ),
    )
    # print(response)

    return response


def start_conversation_study(user_id, user_name, conversation_id):
    conversation_history = db["conversations"].find_one(
        {"_id": ObjectId(conversation_id), "userid": user_id}
    )
    if conversation_history:
        conversation = conversation_history["conversation"]
        conversation_text_list = []
        for item in conversation:
            try:
                # 한글 주석: ensure_ascii=False로 한글이 깨지지 않게 함, indent 없이 한 줄로
                conversation_text_list.append(json.dumps(item, ensure_ascii=False))
            except Exception as e:
                # 변환 실패시 str로 fallback
                conversation_text_list.append(str(item))

        conversation_text = "\n".join(conversation_text_list)

        report = get_phrases(conversation_text)
        phrases = report.parsed["expressions"]
        # print(phrases)
        response = {
            "recommended_phrases": phrases,
            "answer": "Hello, I'm your study tutor, zylo! \nI'll help you practice your speech based on your previous conversation.\nAre you ready?",
            "answer_kor": "안녕하세요, 저는 당신의 study 튜터 zylo에요! \n당신의 이전 대화를 바탕으로 스피치 연습을 도와드릴게요. \n준비 됐나요?",
        }

        return response
    else:
        return None
    # 나중에 DB에 리포트 저장하는거 추가
    # phrases 이용


study_response_schema = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "transcript": types.Schema(
            type=types.Type.STRING,
            description="A precise, verbatim transcript of the user's audio. It should be clean, grammatically correct, and must not contain any filler words (like 'um' or 'uh') or conversational replies. This field represents the user's raw query.",
        ),
        "response": types.Schema(
            type=types.Type.STRING,
            description="A helpful and friendly AI response as the Zylo persona.",
        ),
        "korean_translation": types.Schema(
            type=types.Type.STRING,
            description="Translation of Zylo's response in Korean. Translation of Zylo's answer into Korean. Zylo's English answer must not appear as is.",
        ),
    },
    required=["transcript", "response", "korean_translation"],
)


def generate_llm_response_study(audio_bytes, conversation_history, recommended_phrases):
    contents = [
        *conversation_history,
        {
            "role": "user",
            "parts": [types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")],
        },
    ]

    # 3. 프롬프트 생성 (SYSTEM_PROMPTS.py의 함수 사용)
    study_prompt = create_study_prompt(recommended_phrases)

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=study_response_schema,
            system_instruction=study_prompt,
        ),
    )

    json_text = response.candidates[0].content.parts[0].text
    # print(json_text)
    result = json.loads(json_text)

    return result
