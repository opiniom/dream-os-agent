import os
import json
import datetime
import tempfile
import threading
import time
import google.generativeai as genai

class DreamSynthesizer:
    """
    'dream_trigger' 이벤트 발생 시 백그라운드에서 실행되어 
    대화 기록과 작업 로그를 분석하고, Gemini API(gemini-1.5-pro)를 통해 
    persona_profile.json과 project_context.md를 갱신(Atomic Write 방식)하는 클래스입니다.
    """
    def __init__(self, memory_manager, max_runs_per_hour=5, max_runs_per_day=20, model_name="gemini-2.5-pro"):
        self.manager = memory_manager
        self.max_runs_per_hour = max_runs_per_hour
        self.max_runs_per_day = max_runs_per_day
        self.model_name = model_name
        
        self.runs_log_path = os.path.join(self.manager.logs_dir, "dream_runs.json")
        self.persona_profile_path = os.path.join(self.manager.root_dir, ".agent_memory", "persona_profile.json")
        self.project_context_path = os.path.join(self.manager.root_dir, "project_context.md")
        
        self.lock = threading.Lock()

    def _atomic_write(self, file_path, content, is_json=False):
        """데이터 깨짐을 방지하기 위해 임시 파일에 쓰고 원자적으로 교체하는 Atomic Write 방식을 적용합니다."""
        dir_name = os.path.dirname(file_path)
        os.makedirs(dir_name, exist_ok=True)
        # 동일한 디렉토리에 임시 파일 생성
        fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                if is_json:
                    json.dump(content, f, ensure_ascii=False, indent=2)
                else:
                    f.write(content)
            # os.replace는 원자적(Atomic) 교체를 보장합니다.
            os.replace(temp_path, file_path)
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise e

    def check_rate_limit(self):
        """가동 횟수 제한(Rate Limit)을 검사합니다."""
        with self.lock:
            if not os.path.exists(self.runs_log_path):
                return True, "No runs recorded yet."
            
            try:
                with open(self.runs_log_path, "r", encoding="utf-8") as f:
                    runs = json.load(f)
                    if not isinstance(runs, list):
                        runs = []
            except Exception as e:
                print(f"[Warning] Failed to read run log. Resetting run log. Error: {e}")
                runs = []

            now = datetime.datetime.now()
            hour_ago = now - datetime.timedelta(hours=1)
            day_ago = now - datetime.timedelta(days=1)

            valid_runs = []
            for r in runs:
                try:
                    dt = datetime.datetime.fromisoformat(r)
                    valid_runs.append(dt)
                except ValueError:
                    pass
            
            runs_last_hour = [r for r in valid_runs if r > hour_ago]
            runs_last_day = [r for r in valid_runs if r > day_ago]

            if len(runs_last_hour) >= self.max_runs_per_hour:
                return False, f"Rate limit exceeded: {len(runs_last_hour)} runs in the last hour (Max: {self.max_runs_per_hour})"
            
            if len(runs_last_day) >= self.max_runs_per_day:
                return False, f"Rate limit exceeded: {len(runs_last_day)} runs in the last 24 hours (Max: {self.max_runs_per_day})"
            
            return True, "Under limits"

    def record_run(self):
        """실행 이력을 안전하게 기록합니다."""
        with self.lock:
            runs = []
            if os.path.exists(self.runs_log_path):
                try:
                    with open(self.runs_log_path, "r", encoding="utf-8") as f:
                        runs = json.load(f)
                        if not isinstance(runs, list):
                            runs = []
                except Exception:
                    runs = []
            
            runs.append(datetime.datetime.now().isoformat())
            runs = runs[-100:]  # 최근 100건만 유지하여 크기 관리
            
            try:
                self._atomic_write(self.runs_log_path, runs, is_json=True)
            except Exception as e:
                print(f"[Error] Failed to record run: {e}")

    def synthesize_memory(self):
        """동기 방식으로 메모리 합성을 실행합니다 (스레드 내부에서 주로 호출됨)."""
        print("[Info] Starting Dreaming background memory synthesis...")
        
        # 1. Rate Limit 체크
        allowed, msg = self.check_rate_limit()
        if not allowed:
            print(f"[Warning] Dreaming skipped: {msg}")
            return False

        # 2. 로그 파일 존재 확인 및 로드
        chat_path = self.manager.chat_history_path
        task_path = self.manager.task_log_path

        chat_logs = []
        task_logs = []

        if os.path.exists(chat_path):
            try:
                with open(chat_path, "r", encoding="utf-8") as f:
                    chat_logs = json.load(f)
            except Exception as e:
                print(f"[Error] Failed to load chat history logs: {e}")

        if os.path.exists(task_path):
            try:
                with open(task_path, "r", encoding="utf-8") as f:
                    task_logs = json.load(f)
            except Exception as e:
                print(f"[Error] Failed to load task execution logs: {e}")

        # 로그가 하나도 없으면 요약할 내용이 없으므로 조기 종료
        if not chat_logs and not task_logs:
            print("[Info] No chat or task logs found. Skipping memory synthesis.")
            return True

        # 3. Gemini API 초기화
        try:
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                print("[Error] GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set. Cannot synthesize memory.")
                return False
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(self.model_name)
        except Exception as e:
            print(f"[Error] Failed to configure Gemini API: {e}")
            return False

        # 4. 프롬프트 생성
        chat_text = json.dumps(chat_logs, ensure_ascii=False, indent=2)
        task_text = json.dumps(task_logs, ensure_ascii=False, indent=2)
        
        prompt = f"""
다음은 AI 어시스턴트와 사용자의 대화 로그 및 작업 실행 기록입니다.
이 정보들을 분석하여 사용자의 프로필 및 선호도(Persona Profile)와 현재 작업 중인 프로젝트의 상세 상황(Project Context)을 요약 및 추출해 주세요.

[대화 기록 (Chat History)]
{chat_text}

[작업 실행 로그 (Task Logs)]
{task_text}

반드시 아래 명시된 구조화된 JSON 형식으로만 응답해야 합니다. 다른 서설이나 마크다운 코드 블록 표시(예: ```json)는 제외하고 순수 JSON 데이터만 반환하세요.

JSON 출력 형식 스키마:
{{
  "persona_profile": {{
    "user_name": "사용자 이름 (알 수 없는 경우 빈 문자열)",
    "work_style": "사용자의 작업 스타일 (마크다운 포맷 가능)",
    "preferred_technologies": ["사용 기술 스택 리스트"],
    "other_preferences": "기타 선호 사항 요약"
  }},
  "project_context": {{
    "project_name": "프로젝트 이름 (기본값: 'Dream OS Agent')",
    "core_structure": "프로젝트의 핵심 구조 요약 (마크다운 포맷 가능)",
    "recent_activity": ["최근 수행한 주요 활동 리스트"],
    "completed_tasks": ["완료된 세부 작업/기능 리스트"],
    "pending_tasks": ["앞으로 수행해야 할 남은 작업/기능 리스트"],
    "additional_notes": "기타 특이사항 및 중요 메모"
  }}
}}
"""

        # 5. Gemini API 호출
        try:
            self.record_run()
            
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            response_text = response.text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            result = json.loads(response_text)
        except Exception as e:
            print(f"[Error] Failed to generate or parse Gemini API response: {e}")
            return False

        # 6. 결과 파일 작성 (Atomic Write)
        try:
            persona_data = result.get("persona_profile", {})
            self._atomic_write(self.persona_profile_path, persona_data, is_json=True)
            print(f"[Info] Successfully updated persona profile at {self.persona_profile_path}")

            project_data = result.get("project_context", {})
            md_content = self._format_project_context_markdown(project_data)
            self._atomic_write(self.project_context_path, md_content, is_json=False)
            print(f"[Info] Successfully updated project context at {self.project_context_path}")
            
            return True
        except Exception as e:
            print(f"[Error] Failed to write memory files: {e}")
            return False

    def _format_project_context_markdown(self, context_data):
        """구조화된 project_context JSON 데이터를 마크다운 파일로 포맷팅합니다."""
        proj_name = context_data.get("project_name", "Dream OS Agent")
        core_struct = context_data.get("core_structure", "")
        recent_act = context_data.get("recent_activity", [])
        completed = context_data.get("completed_tasks", [])
        pending = context_data.get("pending_tasks", [])
        notes = context_data.get("additional_notes", "")
        
        md = []
        md.append(f"# 🌌 Project Context: {proj_name}")
        md.append("")
        md.append("## 🏗️ Core Structure")
        if core_struct:
            md.append(core_struct)
        else:
            md.append("- No structure info parsed.")
        md.append("")
        md.append("## 📈 Recent Activity")
        if recent_act:
            for act in recent_act:
                md.append(f"- {act}")
        else:
            md.append("- No recent activity logged.")
        md.append("")
        md.append("## ── Completed Tasks")
        if completed:
            for t in completed:
                md.append(f"- [x] {t}")
        else:
            md.append("- No completed tasks logged.")
        md.append("")
        md.append("## ── Pending Tasks")
        if pending:
            for t in pending:
                md.append(f"- [ ] {t}")
        else:
            md.append("- No pending tasks logged.")
        md.append("")
        md.append("## 📝 Additional Notes")
        if notes:
            md.append(notes)
        else:
            md.append("- No additional notes.")
        md.append("")
        return "\n".join(md)

    def synthesize_memory_async(self):
        """독립 스레드에서 백그라운드로 메모리 합성을 비동기 실행합니다."""
        t = threading.Thread(target=self.synthesize_memory, daemon=True)
        t.start()
        return t

    async def synthesize_memory_asyncio(self):
        """asyncio 비동기 이벤트 루프 내에서 스레드를 활용해 논블로킹으로 기동합니다."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.synthesize_memory)


# ==========================================
# 단위 테스트 코드 (독립 실행 확인용)
# ==========================================
def run_tests():
    from unittest.mock import MagicMock
    from agent_memory import AgentMemoryManager

    print("=== Dreaming & Gemini API 단위 테스트 시작 ===")
    
    # 테스트 1: Rate Limiter 가동 횟수 제한 검증
    with tempfile.TemporaryDirectory() as tmpdir:
        print("\n[Test 1] Rate Limiter 동작 검증 (임시 디렉토리 사용)")
        manager = AgentMemoryManager(root_dir=tmpdir)
        # 시간당 최대 2회 제한으로 인스턴스 생성
        synthesizer = DreamSynthesizer(manager, max_runs_per_hour=2, max_runs_per_day=5)
        
        # 첫 번째 가동 기록
        assert synthesizer.check_rate_limit()[0] is True, "첫 가동 제한 검사를 통과하지 못했습니다."
        synthesizer.record_run()
        
        # 두 번째 가동 기록
        assert synthesizer.check_rate_limit()[0] is True, "두 번째 가동 제한 검사를 통과하지 못했습니다."
        synthesizer.record_run()
        
        # 세 번째 가동 기록 시도 -> 차단되어야 함
        allowed, msg = synthesizer.check_rate_limit()
        assert allowed is False, "가동 제한 초과 시에도 가동 허용 상태가 리턴되었습니다."
        print(f"-> Rate Limiter 정상 차단 확인: {msg}")

    # 테스트 2: 빈 로그 조기 리턴 검증
    with tempfile.TemporaryDirectory() as tmpdir:
        print("\n[Test 2] 대화 및 작업 로그가 없을 때 early exit 여부 검증")
        manager = AgentMemoryManager(root_dir=tmpdir)
        synthesizer = DreamSynthesizer(manager)
        
        # 로그가 없으므로 API 키가 없어도 바로 True(성공)를 리턴해야 함
        success = synthesizer.synthesize_memory()
        assert success is True, "빈 로그 상태에서 초기 종료가 실패했습니다."
        print("-> 빈 로그 검사 완료 (Gemini API 호출 없이 무부하 종료 확인).")

    # 테스트 3: Gemini API 및 Atomic Write 성공 흐름 모킹 검증
    with tempfile.TemporaryDirectory() as tmpdir:
        print("\n[Test 3] Gemini API 응답 분석, 마크다운 변환 및 Atomic Write 검증 (Mocking 활용)")
        manager = AgentMemoryManager(root_dir=tmpdir)
        
        # 로그 생성
        manager.save_chat_message("user", "안드로이드 앱의 MainActivity 레이아웃을 ConstraintLayout으로 수정해줘.")
        manager.save_chat_message("ai", "예, UI 레이아웃을 완성했습니다.")
        manager.log_task_execution("modify_file", {"file": "activity_main.xml"}, True)
        
        synthesizer = DreamSynthesizer(manager)
        
        # 임의의 API Key 환경 변수 강제 주입
        os.environ["GEMINI_API_KEY"] = "MOCK_KEY"
        
        # Gemini API 모킹
        mock_response = MagicMock()
        mock_response.text = """
        {
          "persona_profile": {
            "user_name": "홍길동",
            "work_style": "효율적인 레이아웃 구성을 선호함",
            "preferred_technologies": ["Kotlin", "Android Jetpack"],
            "other_preferences": "어두운 테마 UI 선호"
          },
          "project_context": {
            "project_name": "MyAndroidApp",
            "core_structure": "app -> src -> main -> res -> layout -> activity_main.xml",
            "recent_activity": ["MainActivity 레이아웃 ConstraintLayout으로 수정"],
            "completed_tasks": ["ConstraintLayout 구현 완료"],
            "pending_tasks": ["RecyclerView 어댑터 구현", "테스트 코드 작성"],
            "additional_notes": "SDK 버전 34 기준 타겟팅됨"
          }
        }
        """
        
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        
        # API 호출 부분 가로채기
        genai.GenerativeModel = MagicMock(return_value=mock_model)
        
        # 실행
        success = synthesizer.synthesize_memory()
        assert success is True, "메모리 합성에 실패했습니다."
        
        # 생성된 파일 검증
        assert os.path.exists(synthesizer.persona_profile_path), "persona_profile.json 파일이 생성되지 않았습니다."
        assert os.path.exists(synthesizer.project_context_path), "project_context.md 파일이 생성되지 않았습니다."
        
        # persona_profile.json 내용물 확인
        with open(synthesizer.persona_profile_path, "r", encoding="utf-8") as f:
            persona = json.load(f)
            assert persona["user_name"] == "홍길동", "요약 추출된 이름이 맞지 않습니다."
            assert "Android Jetpack" in persona["preferred_technologies"], "요약 추출된 기술 스택이 누락되었습니다."
            
        # project_context.md 내용물 확인
        with open(synthesizer.project_context_path, "r", encoding="utf-8") as f:
            md_text = f.read()
            assert "# 🌌 Project Context: MyAndroidApp" in md_text, "마크다운 제목 형식이 올바르지 않습니다."
            assert "- [x] ConstraintLayout 구현 완료" in md_text, "완료 리스트 마크다운 형식이 누락되었습니다."
            assert "- [ ] RecyclerView 어댑터 구현" in md_text, "진행예정 리스트 마크다운 형식이 누락되었습니다."
            
        print("-> Gemini API 호출 결과 분석 및 파일 원자적 갱신 완료 검증 성공.")

    print("\n=== 모든 단위 테스트가 성공적으로 완료되었습니다! ===")

if __name__ == "__main__":
    run_tests()
