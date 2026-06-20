# 🌌 Desktop Mirror Agent (DMA)

바탕화면에 투명하게 상주하며 사용자의 화면을 인지하고 컴퓨터를 제어하는 'OS World' 기반의 나만의 맞춤형 AI 어시스턴트 프로젝트입니다. 구글 Gemini API와 로컬 Dreaming 메모리 아키텍처를 결합하여 빌드합니다.

- **Official Repository:** https://github.com/opiniom/dream-os-agent

---

## 🎯 최종 프로젝트 목표 (Core Vision)
1. **투명 오버레이 UI:** 사용자 작업 공간을 방해하지 않는 투명 위젯 레이아웃 및 글로벌 단축키(`Ctrl+F1`) 제어.
2. **시각 기반 OS 제어:** 화면 캡처 및 그리드 오버레이(Set-of-Mark)를 통한 정밀한 마우스/키보드 제어 및 시스템 명령어 실행.
3. **Dreaming 백그라운드 메모리:** 사용자가 쉴 때(Idle 5분) 대화 로그를 리팩토링하여 `project_context.md`와 `persona_profile.json`을 스스로 갱신하는 고도화된 기억 시스템.

## 🚀 개발 프로세스 및 Git 이슈(Issues) 활용 규칙
본 프로젝트는 안티그래비티 IDE와 깃허브 이슈(GitHub Issues)를 연동하여 체계적으로 빌드합니다.
1. **이슈 기반 개발:** 모든 기능 추가, 버그 수정, 모듈 개발은 [dream-os-agent Issues](https://github.com/opiniom/dream-os-agent/issues) 페이지에서 이슈를 먼저 생성한 후 진행합니다.
2. **이슈 템플릿:** 이슈 생성 시 `[모듈 번호] 기능 이름` 형태로 제목을 작성하고, 세부 기능 체크리스트를 명시합니다.
3. **커밋 메시지:** 코드를 커밋하거나 안티그래비티로 반영할 때 반드시 해당 이슈 번호를 참조합니다. (예: `feat: 모듈 6-1 기억 폴더 자동 생성 구현 (#1)`)

... (이하 기존 아키텍처 및 폴더 구조 내용) ...
