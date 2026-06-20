import os
import json
import datetime
import threading
import time

class AgentMemoryManager:
    """
    프로젝트 루트 폴더 내의 `.agent_memory/raw_logs/` 디렉토리를 자동으로 관리하며,
    대화 기록 및 작업 실행 로그를 JSON 파일 형태로 안전하게 기록하는 클래스입니다.
    """
    def __init__(self, root_dir=None):
        if root_dir is None:
            # 기본값으로 현재 작업 디렉토리(프로젝트 루트)를 사용합니다.
            root_dir = os.path.abspath(os.getcwd())
        
        self.root_dir = root_dir
        self.logs_dir = os.path.join(self.root_dir, ".agent_memory", "raw_logs")
        self.chat_history_path = os.path.join(self.logs_dir, "chat_history.json")
        self.task_log_path = os.path.join(self.logs_dir, "task_log.json")
        
        self._ensure_dir_exists()
        self.file_lock = threading.Lock()

    def _ensure_dir_exists(self):
        """로그 디렉토리가 없으면 자동으로 생성합니다."""
        try:
            os.makedirs(self.logs_dir, exist_ok=True)
        except Exception as e:
            print(f"[Error] Failed to create logs directory at {self.logs_dir}: {e}")

    def _append_to_json_file(self, file_path, new_item):
        """JSON Array 파일에 새로운 객체를 스레드 세이프하고 예외 처리를 포함하여 누적 저장합니다."""
        with self.file_lock:
            data = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            data = json.loads(content)
                        if not isinstance(data, list):
                            data = []
                except (json.JSONDecodeError, IOError) as e:
                    # 파일 손상 시 백업 후 빈 배열로 초기화하여 새 데이터가 유실되지 않도록 합니다.
                    print(f"[Warning] Error reading {file_path}. Resetting file. Error: {e}")
                    backup_path = file_path + ".bak"
                    try:
                        if os.path.exists(file_path):
                            os.replace(file_path, backup_path)
                            print(f"[Info] Corrupted file backed up to {backup_path}")
                    except Exception as backup_err:
                        print(f"[Error] Failed to backup corrupted file: {backup_err}")
                    data = []
            
            data.append(new_item)
            
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except IOError as e:
                print(f"[Error] Failed to write data to {file_path}: {e}")

    def save_chat_message(self, role, message):
        """
        사용자와 AI의 대화 내역을 타임스탬프와 함께 `chat_history.json`에 누적 저장합니다.
        """
        timestamp = datetime.datetime.now().isoformat()
        item = {
            "timestamp": timestamp,
            "role": role,
            "message": message
        }
        self._append_to_json_file(self.chat_history_path, item)

    def log_task_execution(self, action, details, success):
        """
        에이전트가 수행한 모든 OS 제어 작업의 결과를 `task_log.json`에 기록합니다.
        """
        timestamp = datetime.datetime.now().isoformat()
        item = {
            "timestamp": timestamp,
            "action": action,
            "details": details,
            "success": success
        }
        self._append_to_json_file(self.task_log_path, item)


class DreamTimer:
    """
    사용자의 입력이나 상호작용이 없을 때 백그라운드 데몬 스레드에서 감시하며,
    지정된 시간(기본 300초) 초과 시 등록된 dream_trigger 콜백(비동기/동기)을 호출하는 클래스입니다.
    """
    def __init__(self, timeout=300, callback=None):
        self.timeout = timeout
        self.callback = callback
        self.last_activity = time.time()
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.triggered = False

    def start(self):
        """감시 데몬 스레드를 시작합니다."""
        with self.lock:
            if self.running:
                return
            self.running = True
            self.triggered = False
            self.last_activity = time.time()
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            print("[Info] DreamTimer started.")

    def poke(self):
        """상호작용이 있을 때 타이머를 리셋합니다."""
        with self.lock:
            self.last_activity = time.time()
            if self.triggered:
                self.triggered = False
                print("[Info] DreamTimer reset (Poked after trigger).")
            else:
                print("[Info] DreamTimer reset (Poked).")

    def stop(self):
        """타이머 스레드를 정지합니다."""
        with self.lock:
            self.running = False
        if self.thread and self.thread.is_alive():
            # 조인 없이 데몬스레드 정지 Flag 변경 후 대기
            pass
        print("[Info] DreamTimer stopped.")

    def _run(self):
        while True:
            with self.lock:
                if not self.running:
                    break
                elapsed = time.time() - self.last_activity
                if elapsed >= self.timeout:
                    if not self.triggered:
                        self.triggered = True
                        print(f"[Event] DreamTimer triggered after {elapsed:.2f}s of inactivity!")
                        if self.callback:
                            try:
                                self.callback()
                            except Exception as e:
                                print(f"[Error] Error during dream callback: {e}")
            time.sleep(0.1)  # 반응 속도를 높이고 CPU 점유율을 줄이기 위해 0.1초 대기


# ==========================================
# 단위 테스트 코드 (독립 실행 확인용)
# ==========================================
def run_tests():
    import tempfile
    import shutil

    print("=== AgentMemory & DreamTimer 단위 테스트 시작 ===")
    
    # 1. 임시 디렉토리 생성 후 Manager 초기화 테스트
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n[Test 1] 임시 디렉토리 생성 및 초기화 검증: {tmpdir}")
        manager = AgentMemoryManager(root_dir=tmpdir)
        
        # 디렉토리 생성 확인
        expected_log_dir = os.path.join(tmpdir, ".agent_memory", "raw_logs")
        assert os.path.exists(expected_log_dir), "로그 디렉토리가 생성되지 않았습니다."
        print("-> 로그 디렉토리 자동 생성 확인 완료.")

        # 2. 대화 기록 저장(save_chat_message) 검증
        print("\n[Test 2] 대화 기록 저장(save_chat_message) 검증")
        manager.save_chat_message("user", "안녕하세요. 오늘 날씨는 어떤가요?")
        manager.save_chat_message("ai", "안녕하세요! 오늘 날씨는 맑고 쾌청합니다.")
        
        assert os.path.exists(manager.chat_history_path), "chat_history.json 파일이 존재하지 않습니다."
        with open(manager.chat_history_path, "r", encoding="utf-8") as f:
            chat_data = json.load(f)
            assert len(chat_data) == 2, f"데이터 개수가 올바르지 않습니다. 기대값: 2, 실제값: {len(chat_data)}"
            assert chat_data[0]["role"] == "user", "첫 번째 메시지의 역할(role)이 올바르지 않습니다."
            assert chat_data[1]["message"] == "안녕하세요! 오늘 날씨는 맑고 쾌청합니다.", "두 번째 메시지 내용이 올바르지 않습니다."
        print("-> 대화 내역 저장 및 읽기 성공.")

        # 3. 작업 로그 기록(log_task_execution) 검증
        print("\n[Test 3] 작업 로그 기록(log_task_execution) 검증")
        manager.log_task_execution("mouse_click", {"x": 120, "y": 450}, True)
        manager.log_task_execution("keyboard_input", {"text": "hello"}, False)

        assert os.path.exists(manager.task_log_path), "task_log.json 파일이 존재하지 않습니다."
        with open(manager.task_log_path, "r", encoding="utf-8") as f:
            task_data = json.load(f)
            assert len(task_data) == 2, f"태스크 로그 개수가 올바르지 않습니다. 기대값: 2, 실제값: {len(task_data)}"
            assert task_data[0]["action"] == "mouse_click", "첫 번째 작업 액션이 올바르지 않습니다."
            assert task_data[1]["success"] is False, "두 번째 작업 성공 여부가 올바르지 않습니다."
        print("-> 작업 실행 로그 저장 및 읽기 성공.")

        # 4. 드림 타이머(DreamTimer) 검증
        print("\n[Test 4] 드림 타이머(DreamTimer) 감시 및 트리거 검증")
        callback_fired = False
        def test_callback():
            nonlocal callback_fired
            callback_fired = True
            print("-> [Callback] dream_trigger 콜백 함수가 성공적으로 호출되었습니다!")

        # 1.초의 타임아웃을 설정한 드림 타이머
        timer = DreamTimer(timeout=1.0, callback=test_callback)
        timer.start()

        # 1.5초 대기 후 트리거 발생 확인
        time.sleep(1.5)
        assert callback_fired is True, "타이머 만료 후 콜백이 실행되지 않았습니다."
        print("-> 비활동 타이머 감시 및 트리거 성공.")

        # 5. 드림 타이머 poke() 리셋 기능 검증
        print("\n[Test 5] 드림 타이머 poke() 리셋 검증")
        callback_fired = False
        timer.poke()  # 트리거 상태 리셋 및 타이머 초기화

        # 0.5초 뒤 poke 호출로 타이머 연장
        time.sleep(0.5)
        timer.poke()
        
        # 다시 0.7초 대기 (이 시점까지 누적 비활동 0.7초이므로 1.0초 미만이라 트리거되지 않아야 함)
        time.sleep(0.7)
        assert callback_fired is False, "poke 호출 후 타이머가 리셋되지 않고 조기 만료되었습니다."
        print("-> poke() 호출을 통한 타이머 리셋 확인.")

        # 추가 0.5초 대기 (마지막 poke로부터 총 1.2초 경과하므로 트리거되어야 함)
        time.sleep(0.5)
        assert callback_fired is True, "poke 이후 타이머가 만료되었음에도 트리거되지 않았습니다."
        print("-> 리셋 후 만료 시간 경과 시 재트리거 확인.")
        
        timer.stop()
        print("-> 드림 타이머 기능 검증 완료.")

    print("\n=== 모든 단위 테스트가 성공적으로 완료되었습니다! ===")


if __name__ == "__main__":
    run_tests()
