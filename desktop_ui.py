import os
import sys
import ctypes
import datetime
from ctypes import windll, c_int, c_bool, c_void_p, Structure, sizeof
from ctypes.wintypes import MSG, HWND

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLineEdit, 
    QTextBrowser, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtGui import QGuiApplication, QFont, QPalette, QColor

# --------------------------------------------------
# Windows OS Native API Definition (ctypes)
# --------------------------------------------------
class ACCENT_POLICY(Structure):
    _fields_ = [
        ("AccentState", c_int),
        ("AccentFlags", c_int),
        ("GradientColor", c_int),
        ("AnimationId", c_int)
    ]

class WINDOWCOMPOSITIONATTRIBDATA(Structure):
    _fields_ = [
        ("Attribute", c_int),
        ("Data", c_void_p),
        ("SizeOfData", c_int)
    ]

# OS Window Style Flags
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

try:
    SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
    GetWindowLong = ctypes.windll.user32.GetWindowLongPtrW
except AttributeError:
    SetWindowLong = ctypes.windll.user32.SetWindowLongW
    GetWindowLong = ctypes.windll.user32.GetWindowLongW

# --------------------------------------------------
# Agent Memory Module Integration
# --------------------------------------------------
try:
    from agent_memory import AgentMemoryManager, DreamTimer
    from dreaming import DreamSynthesizer
    HAS_MEM_MODULE = True
except ImportError:
    HAS_MEM_MODULE = False
    print("[Warning] agent_memory.py or dreaming.py not found. Running in standalone mode.")


class DesktopOverlayWindow(QWidget):
    """
    윈도우 바탕화면에 상주하는 투명한 글래스모피즘 스타일의 오버레이 창입니다.
    마우스 투과(Click-through) 및 전역 단축키 Alt+Shift+D 제어 기능을 네이티브 Windows API로 제어합니다.
    """
    HOTKEY_ID = 101

    # Active / Inactive 상태에 따른 글래스모피즘 QSS 스타일
    # Active: 포커스 획득 및 마우스 조작 가능 상태 (시각적 확인이 쉬운 붉은색 테두리 적용)
    ACTIVE_QSS = """
    QFrame#Container {
        background-color: rgba(25, 25, 25, 200);
        border: 2px solid rgba(255, 0, 0, 220);
        border-radius: 16px;
    }
    """
    # Inactive: 마우스 투과 상태 (시각적 확인이 쉬운 붉은색 테두리 적용)
    INACTIVE_QSS = """
    QFrame#Container {
        background-color: rgba(15, 15, 15, 120);
        border: 2px solid rgba(255, 0, 0, 150);
        border-radius: 16px;
    }
    """

    def __init__(self, memory_manager=None, dream_timer=None):
        super().__init__()
        self.memory_manager = memory_manager
        self.dream_timer = dream_timer
        self.is_click_through = True

        self.init_window_properties()
        self.init_ui_layout()
        self.center_and_position_window()
        self.apply_acrylic_blur()
        
        # 기본 마우스 투과 상태로 시작
        self.enable_click_through()
        
        # 전역 단축키 Alt+Shift+D 등록
        self.register_global_hotkey()

    def init_window_properties(self):
        """윈도우 기본 창 플래그 및 속성 설정"""
        # 프레임 없음, 항상 위에 표시, 툴윈도우(작업표시줄에 아이콘이 나타나지 않음)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowTitle("Dream OS Agent Overlay")

    def init_ui_layout(self):
        """UI 구성 요소 생성 및 배치 (상단 답변 창, 하단 슬림 질문 입력 창 배치)"""
        # 전체를 감싸는 투명 레이아웃
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 글래스모피즘 효과가 적용될 실제 컨테이너 QFrame
        self.container = QFrame()
        self.container.setObjectName("Container")
        self.container.setStyleSheet(self.INACTIVE_QSS)

        # 컨테이너 내의 세로 레이아웃
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(15, 15, 15, 15)
        container_layout.setSpacing(12)

        # [1] 상단 답변 출력창 (QTextBrowser)
        self.output_view = QTextBrowser()
        self.output_view.setFont(QFont("Malgun Gothic", 9))
        self.output_view.setStyleSheet("""
            QTextBrowser {
                background-color: transparent;
                border: none;
                color: rgba(255, 255, 255, 210);
                padding: 4px;
            }
        """)
        self.output_view.setPlaceholderText("여기에 AI 답변이 표시됩니다.")
        
        # 스크롤바 디자인을 슬림하고 깔끔하게 튜닝
        self.output_view.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 40);
                border-radius: 3px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: transparent;
            }
        """)
        container_layout.addWidget(self.output_view)

        # [2] 하단 슬림 질문 입력창 (QLineEdit)
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Alt + Shift + D로 활성화 / 질문을 입력하세요...")
        self.input_box.setFont(QFont("Malgun Gothic", 10))
        self.input_box.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 18);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 8px;
                color: #FFFFFF;
                padding: 8px 12px;
            }
            QLineEdit:focus {
                background-color: rgba(255, 255, 255, 30);
                border: 1px solid rgba(138, 180, 248, 200); /* 은은한 푸른색 포커스 테두리 */
            }
        """)
        self.input_box.returnPressed.connect(self.on_question_submitted)
        container_layout.addWidget(self.input_box)

        main_layout.addWidget(self.container)

    def center_and_position_window(self):
        """메인 모니터 화면 크기를 고려하여 적절한 크기로 우측 하단 배치"""
        # 메인 모니터의 유효 작업 영역(작업표시줄을 제외한 영역) 계산
        screen = QGuiApplication.primaryScreen()
        screen_geom = screen.availableGeometry()

        # 바탕화면에 상주하기에 적당한 슬림한 크기 (가로 380, 세로 500)
        self.width_val = 380
        self.height_val = 500

        # 모니터 우측 하단에서 적당한 마진(우측 30px, 하단 30px)을 준 위치
        x = screen_geom.x() + screen_geom.width() - self.width_val - 30
        y = screen_geom.y() + screen_geom.height() - self.height_val - 30

        self.setGeometry(x, y, self.width_val, self.height_val)
        print(f"[UI] Window positioned at ({x}, {y}) with size {self.width_val}x{self.height_val}")
        print("[UI] [★단축키 안내★] 키보드 단축키 'Alt + Shift + D'를 누르면 바탕화면의 투명 창이 활성화되어 타이핑할 수 있습니다. 'ESC'를 누르면 다시 투과 모드로 돌아갑니다.")

    def apply_acrylic_blur(self):
        """Windows DWM API를 이용해 아크릴 블러(Glassmorphism) 효과 적용"""
        hwnd = int(self.winId())
        
        accent = ACCENT_POLICY()
        accent.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND (Windows 10/11)
        accent.AccentFlags = 2  # 테두리 드로잉 플래그 활성화
        # 0x22000000 -> 어두운 계열의 아크릴 투명도 (ABGR 형식)
        accent.GradientColor = 0x22121212
        accent.AnimationId = 0
        
        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.pointer(accent), c_void_p)
        data.SizeOfData = sizeof(accent)
        
        try:
            ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
            print("[UI] Native Acrylic Blur effect applied successfully.")
        except Exception as e:
            print(f"[Error] Failed to apply Acrylic Blur: {e}")

    # --------------------------------------------------
    # 마우스 투과 및 포커스 관리 로직 (Windows API 호출)
    # --------------------------------------------------
    def enable_click_through(self):
        """마우스 클릭 투과 모드를 활성화하여 바탕화면 조작을 허용합니다."""
        hwnd = int(self.winId())
        style = GetWindowLong(hwnd, GWL_EXSTYLE)
        
        # WS_EX_TRANSPARENT 및 WS_EX_LAYERED 적용
        SetWindowLong(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        
        # 스타일 업데이트 반영
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0, 
            0x0001 | 0x0002 | 0x0004 | 0x0020 # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED
        )
        
        # UI 스타일을 투명도가 높은 INACTIVE_QSS로 갱신
        self.container.setStyleSheet(self.INACTIVE_QSS)
        self.input_box.clearFocus()
        self.is_click_through = True
        print("[UI] Click-through enabled. Window is now passive.")

    def disable_click_through(self):
        """마우스 클릭 투과를 해제하고 창을 최전면 활성화하여 포커스를 확보합니다."""
        hwnd = int(self.winId())
        style = GetWindowLong(hwnd, GWL_EXSTYLE)
        
        # WS_EX_TRANSPARENT 속성 제거
        SetWindowLong(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
        
        # 스타일 업데이트 반영
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0, 
            0x0001 | 0x0002 | 0x0004 | 0x0020
        )
        
        # UI 스타일을 선명한 ACTIVE_QSS로 갱신
        self.container.setStyleSheet(self.ACTIVE_QSS)
        
        # 창 활성화 및 키보드 포커스 먹통 방지를 위해 OS API와 Qt API 연쇄 호출
        self.show()
        self.raise_()
        self.activateWindow()
        
        # WinAPI 최전면 포커싱 보장
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        
        # 입력 상자에 강제 포커스 제공
        self.input_box.setFocus()
        self.is_click_through = False
        print("[UI] Click-through disabled. Focus recovered to Input Box.")

    # --------------------------------------------------
    # 전역 단축키 및 키 이벤트 처리
    # --------------------------------------------------
    def register_global_hotkey(self):
        """Alt + Shift + D 전역 단축키 등록"""
        hwnd = int(self.winId())
        # MOD_ALT = 0x0001, MOD_SHIFT = 0x0004, VK_D = 0x44 (조합 = 0x0005)
        success = ctypes.windll.user32.RegisterHotKey(hwnd, self.HOTKEY_ID, 0x0001 | 0x0004, 0x44)
        if success:
            print("[UI] Global Hotkey Alt+Shift+D registered successfully.")
        else:
            print("[Error] Failed to register Global Hotkey Alt+Shift+D.")

    def unregister_global_hotkey(self):
        """전역 단축키 등록 해제"""
        hwnd = int(self.winId())
        ctypes.windll.user32.UnregisterHotKey(hwnd, self.HOTKEY_ID)
        print("[UI] Global Hotkey unregistered.")

    def nativeEvent(self, event_type, message):
        """Windows OS 이벤트를 가로채 WM_HOTKEY를 필터링합니다."""
        try:
            if event_type == b"windows_generic_MSG" and message:
                addr = int(message)
                if addr != 0:
                    msg = MSG.from_address(addr)
                    if msg.message == 0x0312:  # WM_HOTKEY
                        if msg.wParam == self.HOTKEY_ID:
                            print("[Event] Alt+Shift+D Hotkey detected!")
                            # 단축키 입력 시 마우스 투과 해제하고 활성화
                            self.disable_click_through()
                            return True, 0
        except Exception as e:
            print(f"[Error] nativeEvent crash prevented: {e}")
        return super().nativeEvent(event_type, message)

    def keyPressEvent(self, event):
        """ESC 키 입력 시 투과 모드로 안전하게 복귀"""
        if event.key() == Qt.Key.Key_Escape:
            print("[UI] ESC pressed. Returning to click-through mode.")
            self.enable_click_through()
            event.accept()
        else:
            super().keyPressEvent(event)

    # --------------------------------------------------
    # 비즈니스 로직 및 에이전트 모듈 연동
    # --------------------------------------------------
    def on_question_submitted(self):
        """사용자가 질문을 입력하고 Enter를 눌렀을 때의 동작"""
        question = self.input_box.text().strip()
        if not question:
            return

        self.output_view.append(f"<font color='#8AB4F8'><b>User:</b></font> {question}")
        self.input_box.clear()

        # 질문 기록 및 감시 타이머 Poke 처리
        if HAS_MEM_MODULE and self.memory_manager:
            self.memory_manager.save_chat_message("user", question)
            
        if HAS_MEM_MODULE and self.dream_timer:
            self.dream_timer.poke()

        # 답변 생성 (우선 목업 형식으로 처리하며 모듈 연동)
        self.generate_response(question)

    def generate_response(self, question):
        """가상의 AI 응답을 생성하여 출력창에 표시하고 모듈에 기록"""
        # 예시 응답 템플릿
        reply = f"사용자의 질문 '{question}'을(를) 정상 접수했습니다. 메모리에 기록을 업데이트하고 있으며, 5분간 아무 입력이 없다면 Dreaming 모듈이 백그라운드에서 프로젝트 상태를 요약합니다."
        
        # 화면에 출력
        self.output_view.append(f"<font color='#34A853'><b>AI:</b></font> {reply}")
        self.output_view.append("")  # 여백 추가

        # 답변 기록
        if HAS_MEM_MODULE and self.memory_manager:
            self.memory_manager.save_chat_message("ai", reply)
            self.memory_manager.log_task_execution("simulate_ai_response", {"response": reply}, True)

    # --------------------------------------------------
    # 드래그 앤 드롭 이동 지원 (활성화 상태에서만 드래그 가능)
    # --------------------------------------------------
    def mousePressEvent(self, event):
        if not self.is_click_through and event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.is_click_through and event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, '_drag_position'):
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def closeEvent(self, event):
        """종료 시 단축키 해제 및 타이머 정지"""
        self.unregister_global_hotkey()
        if self.dream_timer:
            self.dream_timer.stop()
        super().closeEvent(event)


# ==========================================
# 실행부 및 테스트 구동
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    manager = None
    timer = None
    
    if HAS_MEM_MODULE:
        # 프로젝트 루트 폴더 지정 (.agent_memory 자동 생성됨)
        manager = AgentMemoryManager()
        
        # 5분(300초) 비활동 시 Dreaming 백그라운드 스레드 기동 콜백 등록
        def trigger_dreaming_callback():
            print("\n[Dream Trigger] 5분간 비활동이 감지되어 Dreaming 합성을 시작합니다...")
            synthesizer = DreamSynthesizer(manager)
            # 비동기 스레드 기동
            synthesizer.synthesize_memory_async()

        # 실테스트를 위해 비활동 제한 시간 기본 300초로 설정
        timer = DreamTimer(timeout=300.0, callback=trigger_dreaming_callback)
        timer.start()
        
        print("[Info] Agent Memory Manager & Dream Timer initialized and connected.")

    # UI 윈도우 생성 및 가시화
    window = DesktopOverlayWindow(memory_manager=manager, dream_timer=timer)
    window.show()
    
    print("\n=== 바탕화면 투명 에이전트 창 구동 중 ===")
    print("- 단축키: Alt + Shift + D (마우스 투과 해제 및 텍스트 박스 포커싱)")
    print("- 단축키: ESC (마우스 투과 모드 재활성화)")
    print("=========================================\n")
    
    sys.exit(app.exec())
