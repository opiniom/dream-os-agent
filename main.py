import os
import sys
import threading

# pyautogui가 로드되기 전에 QApplication을 먼저 초기화하여 Qt가 DPI 설정을 정상적으로 수행하도록 유도합니다.
from PyQt6.QtWidgets import QApplication
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

import google.generativeai as genai
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import QMessageBox

# 모듈 로컬 임포트
from agent_memory import AgentMemoryManager, DreamTimer
from dreaming import DreamSynthesizer
from desktop_ui import DesktopOverlayWindow
from computer_control import (
    take_desktop_screenshot,
    click_coordinates,
    execute_system_command,
    open_browser_url
)

class GeminiWorker(QThread):
    """
    Gemini 1.5 Pro와의 대화 및 Function Calling 루프를 
    PyQt6 UI 스레드를 방해하지 않고 독립 실행하는 백그라운드 스레드입니다.
    """
    output_signal = pyqtSignal(str)          # 출력창 텍스트 업데이트 신호
    status_signal = pyqtSignal(str)          # 상태 메시지 업데이트 신호
    request_approval = pyqtSignal(str)       # UI 스레드로 팝업 요청 신호
    finished_signal = pyqtSignal(bool)       # 작업 완료 신호

    def __init__(self, memory_manager, user_query, model_name="gemini-2.5-pro"):
        super().__init__()
        self.memory = memory_manager
        self.query = user_query
        self.model_name = model_name
        
        # UI 스레드와의 연동을 위한 동기화 이벤트 및 전달자 변수
        self.approval_event = threading.Event()
        self.approval_granted = False

    def set_approval_result(self, granted: bool):
        """UI 스레드에서 사용자의 답변 선택 후 호출하여 이벤트를 해제합니다."""
        self.approval_granted = granted
        self.approval_event.set()

    def run(self):
        try:
            self.status_signal.emit("프로젝트 컨텍스트 분석 중...")
            
            # 1. project_context.md 자동 분석 및 최상단 주입 (방어적 예외 처리)
            context = ""
            paths = [
                os.path.join(self.memory.root_dir, ".agent_memory", "project_context.md"),
                os.path.join(self.memory.root_dir, "project_context.md")
            ]
            for p in paths:
                if os.path.exists(p):
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            context = f.read().strip()
                            break
                    except Exception as e:
                        print(f"[Warning] Failed to read project context file: {e}")
            
            base_instruction = """
You are a powerful agentic AI coding and desktop assistant.
You can control the computer using the provided tools.
Analyze the user's request and the screenshot (with grid overlay).
If you need to click something, find its coordinates on the grid and call the click_coordinates tool.
If you need to execute a command, use execute_system_command.
If you need to open a URL, use open_browser_url.
Always write a concise explanation of what you are doing.
"""
            # 컨텍스트 요약본이 있으면 최상단 병합 주입
            system_instruction = base_instruction
            if context:
                system_instruction = f"Project Context:\n{context}\n\n{base_instruction}"

            # 2. Gemini API 키 인증 및 기동
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                self.output_signal.emit("<font color='#FF5252'>[Error] GEMINI_API_KEY 또는 GOOGLE_API_KEY 환경 변수가 설정되어 있지 않습니다.</font>")
                self.finished_signal.emit(False)
                return

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=self.model_name,
                tools=[click_coordinates, execute_system_command, open_browser_url],
                system_instruction=system_instruction
            )

            # 3. 화면 캡처 기동
            self.status_signal.emit("화면 캡처 중...")
            screenshot = take_desktop_screenshot()

            # 4. Chat 세션 기동
            self.status_signal.emit("AI 분석 및 질의 중...")
            chat = model.start_chat()
            response = chat.send_message([screenshot, self.query])

            # 5. Function Calling 반응 분석 루프
            while True:
                function_calls = []
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.function_call:
                            function_calls.append(part.function_call)

                # 최종 AI 텍스트 응답이 생성되었을 경우 출력창 업데이트 및 저장
                if response.text:
                    self.output_signal.emit(f"<font color='#34A853'><b>AI:</b></font> {response.text}")
                    self.memory.save_chat_message("ai", response.text)

                if not function_calls:
                    # 수행할 도구가 없으면 루프 탈출
                    break

                # 도구 순차 실행
                for fc in function_calls:
                    name = fc.name
                    args = dict(fc.args)
                    
                    action_desc = ""
                    is_dangerous = False

                    # 도구 감시 조건 판단
                    if name == "click_coordinates":
                        is_dangerous = True
                        action_desc = f"마우스 클릭 (좌표: {args.get('x')}, {args.get('y')})"
                    elif name == "execute_system_command":
                        cmd = args.get("cmd", "")
                        action_desc = f"시스템 명령어 실행: '{cmd}'"
                        dangerous_keywords = ["rm", "del", "format", "shutdown", "kill", "remove", "delete", "clean"]
                        if any(k in cmd.lower() for k in dangerous_keywords):
                            is_dangerous = True
                    elif name == "open_browser_url":
                        is_dangerous = True
                        action_desc = f"기본 브라우저 웹사이트 오픈 (URL: {args.get('url')})"

                    # 6. 승인 팝업 안전장치 (QThread 시그널 동기 대기식 기동)
                    if is_dangerous:
                        self.status_signal.emit("사용자 실행 대기 중...")
                        self.approval_event.clear()
                        # UI 스레드로 팝업 신호 전달
                        self.request_approval.emit(action_desc)
                        # UI 답변이 set_approval_result로 도착할 때까지 대기
                        self.approval_event.wait()
                        approved = self.approval_granted
                    else:
                        approved = True

                    # 7. 실행 결정 및 기록
                    if approved:
                        self.output_signal.emit(f"<font color='#FFD700'>[System] AI가 요청한 '{action_desc}'을(를) 승인하여 실행합니다.</font>")
                        # 실제 동작 호출
                        result_dict = self._run_local_tool(name, args)
                        success = result_dict.get("success", True)
                        result_str = result_dict.get("result", "")
                        # 작업 로그 기록
                        self.memory.log_task_execution(name, args, success)
                    else:
                        self.output_signal.emit(f"<font color='#FF7043'>[System] AI가 요청한 '{action_desc}' 실행이 사용자에 의해 거부되었습니다.</font>")
                        result_str = "Error: User denied execution of this action."
                        self.memory.log_task_execution(name, args, False)

                    # 8. 도구 결과 피드백 전송 후 다음 응답 확인
                    self.status_signal.emit("실행 결과 피드백 중...")
                    response_part = genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=name,
                            response={"result": str(result_str)}
                        )
                    )
                    response = chat.send_message(response_part)

            self.status_signal.emit("대화 완료")
            self.finished_signal.emit(True)

        except Exception as e:
            self.output_signal.emit(f"<font color='#FF5252'>[Error] 가동 중 오류 발생: {e}</font>")
            self.finished_signal.emit(False)

    def _run_local_tool(self, name, args):
        """로컬 자동화 툴셋 실행 래퍼"""
        try:
            if name == "click_coordinates":
                x = int(args.get("x", 0))
                y = int(args.get("y", 0))
                success = click_coordinates(x, y)
                return {"success": success, "result": "Click succeeded." if success else "Click failed."}
                
            elif name == "execute_system_command":
                cmd = str(args.get("cmd", ""))
                bg = bool(args.get("background", False))
                res = execute_system_command(cmd, background=bg)
                if bg:
                    return {"success": True, "result": f"Started background process PID: {res.get('pid')}"}
                else:
                    return {
                        "success": res.get("returncode") == 0,
                        "result": f"stdout: {res.get('stdout')}\nstderr: {res.get('stderr')}\ncode: {res.get('returncode')}"
                    }
                    
            elif name == "open_browser_url":
                url = str(args.get("url", ""))
                success = open_browser_url(url)
                return {"success": success, "result": "URL opened." if success else "Failed to open URL."}
                
            return {"success": False, "result": f"Unknown tool name: {name}"}
        except Exception as e:
            return {"success": False, "result": f"Local tool crash: {e}"}


class Orchestrator:
    """
    모든 서브시스템(UI, Memory, Dreaming, Tools, Gemini API)의 기동 및 
    통합 연동 제어를 담당하는 메인 오케스트레이터입니다.
    """
    def __init__(self):
        # 1. 로깅 매니저 기동
        self.memory = AgentMemoryManager()

        # 2. 5분 비활동 감시 드림 타이머 기동
        def trigger_dreaming_callback():
            print("\n[Dream Trigger] 5분간 미사용 상태가 감지되어 Dreaming 합성을 백그라운드 구동합니다...")
            synthesizer = DreamSynthesizer(self.memory)
            synthesizer.synthesize_memory_async()

        self.timer = DreamTimer(timeout=300.0, callback=trigger_dreaming_callback)
        self.timer.start()

        # 3. 투명 데스크톱 UI 창 기동
        self.ui = DesktopOverlayWindow(self.memory, self.timer)
        
        # UI 엔터 입력 리스너 리디렉션 연동
        self.ui.input_box.returnPressed.disconnect()
        self.ui.input_box.returnPressed.connect(self.on_user_submit)
        
        self.worker = None

    def on_user_submit(self):
        """사용자가 입력창에 메시지를 보냈을 때"""
        question = self.ui.input_box.text().strip()
        if not question:
            return

        # UI 출력
        self.ui.input_box.clear()
        self.ui.output_view.append(f"<font color='#8AB4F8'><b>User:</b></font> {question}")
        self.ui.output_view.append("") # 줄바꿈 여백
        
        # 1. 사용자 질문 대화록 저장 및 타이머 갱신
        self.memory.save_chat_message("user", question)
        self.timer.poke()

        # 중복 입력 방지를 위한 임시 비활성화
        self.ui.input_box.setEnabled(False)
        self.ui.input_box.setPlaceholderText("AI 처리 중...")

        # 2. 백그라운드 분석 스레드(QThread) 기동
        self.worker = GeminiWorker(self.memory, question)
        self.worker.output_signal.connect(self.ui.output_view.append)
        self.worker.status_signal.connect(self.update_status_bar)
        self.worker.request_approval.connect(self.show_approval_popup)
        self.worker.finished_signal.connect(self.on_worker_complete)
        self.worker.start()

    def update_status_bar(self, status):
        """AI 진행 상탯값 반영"""
        self.ui.input_box.setPlaceholderText(f"AI: {status}")

    def show_approval_popup(self, action_desc):
        """UI 스레드 내에서 안전하게 모달 다이얼로그를 구동하여 사용자 승인을 받습니다."""
        # 팝업을 보기 위해 잠시 UI 창을 최상위 상태로 포커스 회수
        self.ui.show()
        self.ui.raise_()
        self.ui.activateWindow()
        
        reply = QMessageBox.question(
            self.ui,
            "AI Action Authorization",
            f"AI 에이전트가 다음 컴퓨터 제어 명령을 실행하려고 합니다.\n\n[명령]: {action_desc}\n\n이 동작을 승인하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        approved = (reply == QMessageBox.StandardButton.Yes)
        
        # 대기 상태인 백그라운드 스레드에 최종 결정 피드백 전달
        if self.worker:
            self.worker.set_approval_result(approved)

    def on_worker_complete(self, success):
        """백그라운드 스레드 종료 시 다시 대기 상태로 전환"""
        self.ui.input_box.setEnabled(True)
        self.ui.input_box.setPlaceholderText("Alt + Shift + D로 활성화 / 질문을 입력하세요...")
        self.ui.input_box.setFocus()
        self.timer.poke()
        self.worker = None


if __name__ == "__main__":
    import traceback
    try:
        # 오케스트레이터 기동
        orchestrator = Orchestrator()
        orchestrator.ui.show()
        
        print("\n=== Dream OS Agent 최종 오케스트레이터(main.py) 구동 중 ===")
        print("- 단축키: Alt + Shift + D (창 활성화 및 입력 포커스)")
        print("- 단축키: ESC (마우스 클릭 투과 패시브 모드)")
        print("- 백그라운드 가동: 사용자가 5분간 미작동 시 메모리 리팩토링 Dreaming 자동 구동")
        print("============================================================\n")
        
        sys.exit(app.exec())
    except Exception as e:
        with open("crash_log.txt", "w", encoding="utf-8") as f:
            f.write(f"Crash occurred: {e}\n")
            f.write(traceback.format_exc())
        print(f"[Crash] {e}")
        traceback.print_exc()
        sys.exit(1)
