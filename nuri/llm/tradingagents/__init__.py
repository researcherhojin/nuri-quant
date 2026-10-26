"""TradingAgents 에서 가져온 코드 (Apache-2.0, 이 디렉터리의 LICENSE).

원본: https://github.com/TauricResearch/TradingAgents 커밋 e8f5503 (2026-10-16).
논문: Xiao et al., "TradingAgents: Multi-Agents LLM Financial Trading Framework", arXiv:2412.20138.

패키지째 의존하지 않는 이유: 분석가가 그래프 안에서 도구로 데이터를 받아 재생할 근거 묶음이 없고,
Ollama 를 OpenAI 호환 API 로 불러 요청별 `num_ctx` 를 못 정하며(docs.ollama.com/api/openai-compatibility),
langchain 의 외부 LLM SDK 들을 끌어온다. 그래서 순수 함수 · 프롬프트만 가져오고 연결부는 우리 것
(`nuri/llm/local_client.py` · `nuri/llm/evidence.py`)을 쓴다.

각 파일 머리에 원본 경로와 바꾼 점을 적는다 (Apache-2.0 §4(b)). 원본에는 NOTICE 파일도, 파일별 · README ·
pyproject 의 저작권 문구도 없다(2026-10-27 확인) — §4(c) 로 보존할 고지가 없어 저작자를 "TauricResearch
TradingAgents contributors" 로 적는다.
"""
