# 새 앱에 연결

`release.json`은 구성 형식 예시다. 이 앱의 실제 applicationId, variant별 Gradle 작업/산출물, 현재 필요한 SDK/JDK, 개발자·문의·방침으로 수정한다. 다른 앱의 계정·데이터 보안·대상 연령·국가 응답을 복사하지 않는다. flavor가 있으면 Release 작업과 APK/AAB 경로도 그 flavor로 바꾼다. Java 21 테스트가 필요하면 `java_version`을 21로 지정한다. NDK/CMake가 필요한 앱만 `android_sdk_packages`에 추가한다.

`bin/play-release --project <앱> doctor`는 누락된 도구·설정을 읽기만 하고 안내한다. `play-declarations questions --json`으로 미정인 앱별 사업·정책 사실을 수집한다. SDK/JDK/Ruby/Bundler와 비공개 서명/서비스 계정 경로는 환경에 한 번 설정한다. 계정 경로가 있으면 bootstrap이 false여도 verify_access/status로 실제 API 준비 상태를 먼저 확인한다. 첫 수동 업로드가 필요하다는 API 응답이 있을 때 Console에서 처리하며, 앱 생성·법적 동의·콘텐츠/서명/테스트 자격은 실제 계정에서 확인한다.

공통 `prepare`가 APK/AAB 코드 일치·서명·16KB·스토어 자료를 검사하고 `preparation.json`, 미승인 `review-<hash>.json`을 만든다. `production_device_checks`에는 앱의 실제 위험에 맞는 실기기 시나리오를 정의한다. `min_sdk`, `max_sdk`, `device_pattern`으로 구형 기기 결과가 최신 기기 검사에 사용되는 것을 막을 수 있다.

앱 전용 검사도 공통 절차에 연결할 수 있다. `artifact_checks`는 셸이 아닌 인수 배열이며 `{aab}`, `{apk}`, `{output}`, `{package_name}`, `{version_name}`, `{version_code}`를 치환한다. 0이 아닌 종료 코드는 제출 전에 실패한다. 예:

```json
"artifact_checks": [["python3", "tools/check_app_security.py", "--apk", "{apk}", "--version", "{version_name}"]]
```

카메라/ADB 패키지명, UI 렌더러, 권한 규칙, 실제 시연 영상은 해당 앱에 둔다. 공통 도구는 특정 앱의 기기 동작을 하드코딩하지 않는다.
