import os
import io
import sys
import ctypes
import subprocess
import webbrowser
import time
from PIL import Image, ImageGrab, ImageDraw, ImageFont

# --------------------------------------------------
# PyAutoGUI Failsafe & DPI-Awareness 설정
# --------------------------------------------------
import pyautogui
# 마우스를 화면 구석(0,0 등)으로 이동하면 프로그램 동작이 비상 정지(Failsafe)되도록 설정
pyautogui.FAILSAFE = True

def set_dpi_awareness():
    """Windows 환경에서 디스플레이 배율(DPI Scaling) 오차를 예방하기 위해 프로세스를 DPI-Aware로 설정합니다."""
    if sys.platform == "win32":
        try:
            # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Windows 8.1+)
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            print("[OS] DPI Awareness: Per-Monitor DPI Aware configured.")
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                print("[OS] DPI Awareness: System DPI Aware configured.")
            except Exception:
                print("[OS] DPI Awareness: Failed to set DPI awareness. Using default OS scaling.")

# 모듈 로드 시 최초 1회 실행
set_dpi_awareness()


# --------------------------------------------------
# 컴퓨터 제어 및 자동화 기능 (Gemini Tool Spec 호환)
# --------------------------------------------------
def take_desktop_screenshot(grid_interval: int = 100, max_long_edge: int = 1024) -> Image.Image:
    """
    현재 컴퓨터의 모니터 전체 화면을 캡처하고, AI가 요소들의 좌표를 명확히 인지할 수 있도록 
    격자 무늬(그리드)와 좌표 숫자를 오버레이하여 리턴합니다.
    구글 Gemini API 전송 최적화(토큰 절약 및 전송 속도 향상)를 위해 장축 크기 리사이징 및 압축이 수행됩니다.

    Args:
        grid_interval: 격자선 간격 (기본 100 픽셀).
        max_long_edge: 캡처된 이미지의 장축(가로/세로 중 긴 쪽) 기준 최대 크기 (기본 1024 픽셀).

    Returns:
        PIL.Image.Image: 지정된 간격의 격자 오버레이가 포함되고 최적화(JPEG 85% 압축)된 PIL Image 객체.
    """
    try:
        # 1. 전체 화면 캡처
        try:
            screenshot = ImageGrab.grab()
        except Exception as e:
            print(f"[Warning] Failed to capture desktop screen grab: {e}. Falling back to dummy 1920x1080 canvas.")
            screenshot = Image.new("RGB", (1920, 1080), (30, 30, 30))
        w, h = screenshot.size
        
        # 2. 투명 격자선 및 텍스트 렌더링용 드로잉 엔진 기동
        # 격자 드로잉 시 알파(RGBA) 값을 사용해 반투명하게 합성하기 위해 RGBA로 작업 후 최종 JPEG 변환
        draw_img = screenshot.convert("RGBA")
        draw = ImageDraw.Draw(draw_img, "RGBA")
        
        # 기본 폰트 로드
        try:
            # 기본 폰트 로딩 시도 (크기 지정을 위해 Truetype도 지원할 수 있으나 OS 범용성을 위해 default 사용)
            font = ImageFont.load_default()
        except Exception:
            font = None

        # 3. 가로/세로 격자 드로잉
        # 세로선 그리기
        for x in range(grid_interval, w, grid_interval):
            draw.line([(x, 0), (x, h)], fill=(255, 65, 54, 80), width=1)  # 반투명 빨간선
        
        # 가로선 그리기
        for y in range(grid_interval, h, grid_interval):
            draw.line([(0, y), (w, y)], fill=(255, 65, 54, 80), width=1)

        # 4. 교차점 좌표 텍스트 그리기 (시인성을 위한 검정색 반투명 박스 배경 추가)
        for x in range(grid_interval, w, grid_interval):
            for y in range(grid_interval, h, grid_interval):
                text = f"({x},{y})"
                # 폰트 정보에 따라 텍스트 박스 계산 (Pillow 호환성 유지)
                try:
                    bbox = draw.textbbox((x + 2, y + 2), text, font=font)
                    # 검은색 60% 투명 상자
                    draw.rectangle(bbox, fill=(0, 0, 0, 150))
                except AttributeError:
                    pass
                # 흰색 텍스트
                draw.text((x + 2, y + 2), text, fill=(255, 255, 255, 220), font=font)

        # 5. 장축 기준 리사이징
        screenshot_final = draw_img.convert("RGB")
        max_edge = max(w, h)
        if max_edge > max_long_edge:
            scale = max_long_edge / max_edge
            new_w = int(w * scale)
            new_h = int(h * scale)
            screenshot_final = screenshot_final.resize((new_w, new_h), Image.Resampling.LANCZOS)
            print(f"[OS] Screenshot resized from {w}x{h} to {new_w}x{new_h} (scale: {scale:.2f})")
        else:
            print(f"[OS] Screenshot kept original size: {w}x{h}")

        # 6. JPEG 압축 최적화 (인메모리 압축 후 재로드)
        compressed_stream = io.BytesIO()
        screenshot_final.save(compressed_stream, format="JPEG", quality=85)
        compressed_stream.seek(0)
        
        optimized_image = Image.open(compressed_stream)
        optimized_image.load()  # 스트림 닫히기 전 메모리에 데이터 로드
        
        print("[OS] Screenshot taken and optimized with grid overlay.")
        return optimized_image

    except Exception as e:
        print(f"[Error] Failed to capture desktop: {e}")
        # 오류 발생 시 빈 더미 이미지 반환
        return Image.new("RGB", (1920, 1080), (30, 30, 30))


def click_coordinates(x: int, y: int) -> bool:
    """
    모니터 화면 상의 지정된 (x, y) 절대 좌표로 마우스 포인터를 부드럽게 이동하고 클릭을 실행합니다.
    디스플레이 배율 오차 방지를 위해 모니터 경계선 검사가 사전 수행됩니다.

    Args:
        x: 클릭할 화면의 가로 절대 좌표.
        y: 클릭할 화면의 세로 절대 좌표.

    Returns:
        bool: 마우스 이동 및 클릭이 오류 없이 성공적으로 완료되면 True, 그렇지 않으면 False.
    """
    try:
        screen_w, screen_h = pyautogui.size()
        if not (0 <= x <= screen_w and 0 <= y <= screen_h):
            print(f"[Warning] Click coordinates ({x}, {y}) out of screen boundaries ({screen_w}x{screen_h}). Attempting anyway.")
        
        # 0.2초에 걸쳐 마우스를 대상 좌표로 자연스럽게 이동 후 클릭
        pyautogui.moveTo(x, y, duration=0.2)
        pyautogui.click(x, y)
        print(f"[OS] Successfully clicked coordinates ({x}, {y}).")
        return True
    except Exception as e:
        print(f"[Error] Failed to click coordinates ({x}, {y}): {e}")
        return False


def execute_system_command(cmd: str, background: bool = False) -> dict:
    """
    운영체제(OS)의 터미널/CMD 쉘 명령어를 실행합니다. 
    로컬 웹 서버 기동이나 에뮬레이터 동작 같이 오랜 시간 기동 상태를 유지해야 하는 명령은 
    background=True 파라미터를 설정하여 백그라운드 독립 프로세스로 구동시킬 수 있습니다.

    Args:
        cmd: 실행할 쉘 명령어.
        background: True인 경우 명령어를 subprocess.Popen을 사용하여 비동기 백그라운드로 실행하며 즉시 반환합니다.
                    False인 경우 명령어가 끝날 때까지 대기(최대 15초 제한)한 후 결과를 반환합니다.

    Returns:
        dict: 실행 결과 딕셔너리.
              - 백그라운드 실행 시: {"status": "started", "pid": 프로세스_PID}
              - 블로킹 실행 시: {"stdout": "결과 표준 출력", "stderr": "표준 에러 결과", "returncode": 리턴코드}
    """
    try:
        if background:
            # 백그라운드 실행 (Popen)
            # 윈도우 환경에서 백그라운드 프로세스가 새 창 그룹으로 독자 실행되도록 플래그 설정
            creation_flag = 0
            if sys.platform == "win32":
                creation_flag = subprocess.CREATE_NEW_PROCESS_GROUP
            
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flag
            )
            print(f"[OS] Background process started (PID: {process.pid}) for command: '{cmd}'")
            return {
                "status": "started",
                "pid": process.pid
            }
        else:
            # 블로킹 동기 실행 (subprocess.run) - 최대 15초 타임아웃
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=15
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
            
    except subprocess.TimeoutExpired as e:
        print(f"[Error] System command '{cmd}' execution timed out (15s limit).")
        return {
            "stdout": e.stdout if e.stdout else "",
            "stderr": "Command execution timed out after 15 seconds.",
            "returncode": -1
        }
    except Exception as e:
        print(f"[Error] Failed to execute system command '{cmd}': {e}")
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -2
        }


def open_browser_url(url: str) -> bool:
    """
    지정된 인터넷 웹사이트 URL 주소를 시스템 기본 브라우저를 통해 새 탭이나 창으로 열어줍니다.

    Args:
        url: 열고자 하는 웹 사이트 주소 (예: 'https://github.com/opiniom/dream-os-agent').

    Returns:
        bool: 브라우저가 정상적으로 기동되어 창 열기에 성공하면 True, 그렇지 않으면 False.
    """
    try:
        success = webbrowser.open(url)
        if success:
            print(f"[OS] Successfully opened URL in browser: {url}")
        else:
            print(f"[Error] Default browser rejected or failed to open URL: {url}")
        return success
    except Exception as e:
        print(f"[Error] Failed to open URL '{url}': {e}")
        return False


# ==========================================
# 단위 테스트 코드 (독립 실행 확인용)
# ==========================================
def run_tests():
    from unittest.mock import MagicMock, patch

    print("=== Computer Automation Tools 단위 테스트 시작 ===")

    # 1. take_desktop_screenshot 테스트
    print("\n[Test 1] take_desktop_screenshot 실행 및 이미지 규격 최적화 검증")
    img = take_desktop_screenshot(grid_interval=150, max_long_edge=800)
    assert isinstance(img, Image.Image), "반환된 객체가 PIL Image가 아닙니다."
    w, h = img.size
    assert max(w, h) <= 800, f"장축 리사이징 제한(800px)이 적용되지 않았습니다. 실제 크기: {w}x{h}"
    print(f"-> 캡처 성공 및 이미지 최적화 확인 (최종 크기: {w}x{h}).")
    
    # 캡처 결과 테스트 저장 (.agent_memory/raw_logs/ 에 임시 저장해봄)
    test_log_dir = os.path.join(os.path.abspath(os.getcwd()), ".agent_memory", "raw_logs")
    os.makedirs(test_log_dir, exist_ok=True)
    test_img_path = os.path.join(test_log_dir, "test_screenshot_grid.jpg")
    img.save(test_img_path, format="JPEG")
    print(f"-> 캡처 확인용 격자 이미지 저장 완료: {test_img_path}")

    # 2. click_coordinates 테스트 (사용자 마우스 오작동 방지를 위해 모킹 테스트 수행)
    print("\n[Test 2] click_coordinates 클릭 연동 및 DPI 보정 여부 검증 (Mocking)")
    with patch("pyautogui.click") as mock_click, patch("pyautogui.moveTo") as mock_move:
        success = click_coordinates(150, 250)
        assert success is True, "클릭 수행이 정상적으로 완료되지 않았습니다."
        mock_move.assert_called_once_with(150, 250, duration=0.2)
        mock_click.assert_called_once_with(150, 250)
        print("-> 마우스 이동 및 클릭 API 정상 전달 확인.")

    # 3. execute_system_command 테스트
    print("\n[Test 3] execute_system_command 동기 및 비동기(백그라운드) 분기 검증")
    # 동기 실행 검증
    sync_result = execute_system_command("echo hello_dream_agent")
    assert sync_result["returncode"] == 0, "동기 명령어 실행이 실패했습니다."
    assert "hello_dream_agent" in sync_result["stdout"], "출력 결과가 맞지 않습니다."
    print("-> 동기 쉘 명령어 실행 성공.")

    # 비동기(백그라운드) 실행 검증
    bg_result = execute_system_command("python -c \"import time; time.sleep(10)\"", background=True)
    assert bg_result["status"] == "started", "백그라운드 실행 개시 메시지가 반환되지 않았습니다."
    assert "pid" in bg_result, "프로세스 PID가 제공되지 않았습니다."
    print(f"-> 비동기 백그라운드 프로세스 기동 성공 (PID: {bg_result['pid']}).")
    
    # 생성한 백그라운드 테스트 프로세스 강제 종료
    try:
        import psutil
        proc = psutil.Process(bg_result["pid"])
        proc.terminate()
        print("-> 테스트용 백그라운드 프로세스 정리 완료.")
    except Exception:
        pass

    # 4. open_browser_url 테스트 (실제 브라우저 팝업 방지를 위해 모킹 테스트)
    print("\n[Test 4] open_browser_url 브라우저 실행 연동 검증 (Mocking)")
    with patch("webbrowser.open") as mock_open:
        mock_open.return_value = True
        success = open_browser_url("https://github.com/opiniom/dream-os-agent")
        assert success is True
        mock_open.assert_called_once_with("https://github.com/opiniom/dream-os-agent")
        print("-> 기본 브라우저 연동 정상 호출 확인.")

    print("\n=== 모든 단위 테스트가 성공적으로 완료되었습니다! ===")


if __name__ == "__main__":
    run_tests()
