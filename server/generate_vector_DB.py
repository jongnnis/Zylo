import os
import json
import chromadb
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv
import hashlib

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")


class GenerateVectorDB:
    def __init__(self, openai_api_key, cache_dir="cache"):
        self.client = OpenAI(api_key=openai_api_key)
        self.cache_dir = cache_dir
        self.chroma_client = chromadb.PersistentClient(path=f"{cache_dir}/chroma_db")

    def get_user_collection(self, user_id):
        """사용자별 컬렉션 생성
        이후에 이 컬렉션을 통해 검색을 수행"""
        collection_name = f"user_{user_id}_conversations"
        return self.chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def create_embedding(self, text):
        """텍스트를 OpenAI 임베딩 벡터로 변환"""
        response = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )

        return response.data[0].embedding

    def save_full_conversation(self, user_id, conversation_history, date):
        """전체 통화 대본을 벡터 DB에 저장
        벡터로 변환해서 저장할 뿐만 아니라, 대본을 그대로 파일 시스템에 저장"""

        # 사용자별 컬렉션 가져오기
        user_collection = self.get_user_collection(user_id=user_id)

        # 전체 대화를 텍스트로 변환
        conversation_text = self._format_conversation_history(
            conversation_history=conversation_history
        )

        # 임베딩 생성
        embedding = self.create_embedding(conversation_text)

        # 통화 메타데이터 생성
        timestamp = datetime.now().isoformat()
        conversation_id = hashlib.md5(f"{user_id}_{timestamp}".encode()).hexdigest()

        # 벡터 DB에 저장
        user_collection.add(
            embeddings=[embedding],
            documents=[conversation_text],
            metadatas=[
                {
                    "user_id": user_id,
                    "timestamp": timestamp,
                    "date": date,
                    "conversation_length": len(conversation_history),
                }
            ],
            ids=[conversation_id],
        )

        # 파일 시스템에 전체 대화 대본 캐시 저장
        self._save_to_file_cache(
            user_id=user_id,
            conversatioin_history=conversation_history,
            timestamp=timestamp,
            date=date,
        )

        return conversation_id

    def _format_conversation_history(self, conversation_history):
        """conversation_history를 검색 가능한 텍스트로 변환
        즉, json형태로 되어있는 conversation_history를 텍스트로 변환"""

        formatted_text = ""

        for turn in conversation_history:
            role = "User" if turn["role"] == "user" else "Zylo"
            text = turn["parts"][0]["text"]
            formatted_text += f"{role}: {text}\n"

        return formatted_text.strip()

    def _save_to_file_cache(self, user_id, conversatioin_history, timestamp, date):
        """파일 시스템에 전체 통화 대본 저장"""
        user_cache_dir = f"{self.cache_dir}/users/{user_id}"
        os.makedirs(user_cache_dir, exist_ok=True)

        # 날짜별 파이로 저장
        date_str = timestamp.split("T")[0]
        time_str = timestamp.split("T")[1].split(".")[0].replace(":", "-")
        cache_file = f"{user_cache_dir}/{date_str}_{time_str}.json"

        # 통화 데이터 저장
        call_data = {
            "timestamp": timestamp,
            "date": date,
            "conversation_history": conversatioin_history,
            "conversation_length": len(conversatioin_history),
        }

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(call_data, f, ensure_ascii=False, indent=2)

    def search_user_conversations(self, user_id, query, n_results=3):
        """특정 사용자의 과거 통화에서 유사한 내용 검색"""
        user_collection = self.get_user_collection(user_id=user_id)
        query_embedding = self.create_embedding(query)

        results = user_collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
        )

        return results


# vector_db = GenerateVectorDB(openai_api_key=openai_api_key, cache_dir="cache")

# user_id = "kairos"  # 예시

# conversation_id = vector_db.save_full_conversation(
#     user_id=user_id,
#     conversation_history=conversation_history,
#     call_duration="00분 30초",
# )

# results = vector_db.search_user_conversations(
#     user_id=user_id,
#     query="Do you know my name?",
#     n_results=1,
# )

# print(results["documents"][0])
