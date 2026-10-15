# 반복 가능한 Google Play 배포

확인 기준일: 2026-10-14. 다음 배포에서는 아래 공식 문서와 해당 계정 Console의 요구사항을 다시 확인한다.

## 산출물과 처리 순서

| 순서 | 결과물 | 최초 등록 | 이후 업데이트 |
| --- | --- | --- | --- |
| 1 | 고정 applicationId, 증가하는 versionCode, versionName, 변경 내역 | 결정 | versionCode 증가; 업로드된 코드는 재사용 불가 |
| 2 | Play 전용 서명 AAB, SHA-256, 서명 인증서, 최종 manifest, 네이티브 검사 | 생성 | 매번 자동 생성·검사 |
| 3 | 제목(30자), 짧은 설명(80자), 상세 설명(4000자), 문의 이메일 | 작성 | 기능·수집 내용 변경 시 갱신 |
| 4 | 아이콘 512×512, feature graphic 1024×500, 실제 앱 스크린샷 최소 2장 | 생성 | UI 변경 시 갱신 |
| 5 | 공개 개인정보처리방침 URL 및 앱 안의 방침, 데이터 보안 답변 | 공개·신고 | 데이터 흐름 변경 시 재검토 |
| 6 | 앱 액세스, 광고, 대상 연령, IARC, 민감 권한/FGS 신고 및 필요한 영상 | Console 입력 | 신고 내용 변경 시 갱신 |
| 7 | 내부 테스트 릴리스, 실제 기기 결과, pre-launch report | Console/API | 자동 업로드 + 결과 확인 |
| 8 | 해당 계정의 비공개 테스트·프로덕션 접근 승인 | 해당되는 경우 | 새 앱마다 계정 요구사항 확인 |
| 9 | 심사 제출, 승인, 출시, Android vitals 확인 | Console | 테스트한 동일 versionCode 승격 |

스크린샷은 JPEG 또는 alpha 없는 PNG, 320~3840px, 긴 변이 짧은 변의 2배 이내. 1080×1920 또는 1080×2160 캡처를 사용한다. Feature graphic은 alpha 없는 PNG/JPEG. 아이콘은 32-bit PNG, 1 MB 이하. 영상은 필요한 권한의 실제 사용자 시작·진행·종료를 보여 주고 심사자가 열 수 있는 링크로 제공한다. 그림이나 모의 화면을 실기기 성공 증거로 사용하지 않는다.

## 최초 Console 설정

1. 개발자 본인/조직·연락처·결제 및 필요한 기기 인증을 완료한다. 앱 생성: 기본 언어, 앱/게임, 무료/유료를 실제 사업 계획대로 설정한다. 무료 앱을 유료 앱으로 바꿀 수 없으므로 임의 결정하지 않는다.
2. 패키지는 첫 AAB로 정해진다. 이후 package ID를 바꾸면 별개 앱이다.
3. Play App Signing을 설정한다. **업로드 키**와 사용자에게 전달되는 **앱 서명 키**는 다르다. 기존 사이드로딩 설치 위에 Play 업데이트를 제공하려면 기존 앱 서명 키와의 호환을 검토한다. 소스에 노출된 기존 키는 새 Play 앱의 신뢰할 수 있는 앱 서명 키로 그대로 채택하지 않는다. Google 생성 키를 선택하면 기존 APK와 서명이 달라질 수 있으므로 최초 전환 시 삭제·재설치가 필요하다. 키 교체·이전은 사용자와 실제 설치 기반을 확인해 결정한다.
4. 내부 테스트에서 첫 AAB를 수동 업로드하고 저장한다. API 도구는 앱 생성과 첫 업로드를 대신하지 못한다. 이후 자동화는 그 앱을 사용한다.
5. 스토어 등록정보, 공개 방침 URL, 국가/지역, 앱 콘텐츠 신고를 채운다. 앱 종류에 따라 추가 Console 항목이 생긴다. 체크리스트를 실제 Console 상태로 갱신한다.
6. 2023-11-13 이후 생성된 개인 계정은 최소 12명, 연속 14일 비공개 테스트 후 프로덕션 접근을 신청해야 한다. 내부 테스트는 이 조건을 대신하지 않는다. 조직/다른 계정은 Console의 실제 조건을 따른다.

## 반복 배포 자동화

- 앱별 선언 사실은 `bin/play-declarations --project <app> questions --json`으로 확인한다. 사용자에게 새로 필요한 사실만 설명·선택지와 함께 소량씩 질문하고, 답변은 `answer --id ... --value ... --source user|code|console`으로 기록한다. 터미널에서는 `interview`가 질문·저장·재개를 수행한다. 다른 앱의 응답은 복사하지 않으며 미정 값은 자동 선택하지 않는다. 조건에 따라 데이터·계정 삭제·건강·금융·정부·접근·FGS 후속 질문이 생긴다. 프로덕션 승격은 `status --require-complete`를 통과해야 하지만 실제 Console 설문·IARC·심사 완료 여부는 별도로 확인한다. 기능·SDK·운영이 달라지면 저장한 사실도 갱신한다.
- 릴리스 설정: `<project>/play/release.json`; 스토어 원본: `fastlane/metadata/android/<locale>/`; 선언·심사 안내: `play/`.
- 최초 업로드 키는 `python3 skills/google-play-release/scripts/create_upload_key.py --output-dir /absolute/private/app-upload --developer DeveloperName`으로 저장소 밖에 생성한다. 이미 있는 키는 회전하거나 덮어쓰지 않는다. 생성한 `signing.json`을 `PLAY_SIGNING_CONFIG` 또는 `prepare --signing-config ...`으로 지정한다. CI는 기존 서명 Secrets를 사용한다. 이 명령은 Play 앱 서명 키를 선택하지 않는다.
- `python3 skills/google-play-release/scripts/release.py prepare`로 빌드·단위 테스트·lint·AAB 감사를 한 번에 실행한다. 기본값은 로컬 준비이며 업로드하지 않는다.
- `check --aab ... --store`는 업로드할 파일 자체와 등록정보를 재검사한다. 대상 API 최소치는 설정에 기록하고 매년 갱신한다. AAB 내부의 모든 64-bit ELF LOAD segment와 RELRO 및 bundletool PAGE_ALIGNMENT_16K를 검사한다.
- 스크린샷/신고 문서만 갱신했으면 `package --aab <기존 AAB>`로 같은 파일을 재검사하고 묶음만 갱신한다. 앱 내부에 포함된 방침을 바꿨다면 AAB를 다시 빌드한다. `bundled_documents` 설정이 원본과 번들의 불일치를 검사한다.
- Cloud 프로젝트에서 Google Play Android Developer API를 활성화하고 서비스 계정을 Play Console의 사용자로 추가한다. 해당 앱의 조회, 스토어 관리, 테스트 트랙 출시 권한을 부여한다. 프로덕션 권한은 필요할 때만 부여한다. 기존 Cloud 프로젝트를 Play 계정에 연결해야 한다는 오래된 안내를 필수로 취급하지 않는다.
- 자격증명은 외부 파일 경로를 `PLAY_SERVICE_ACCOUNT_JSON`으로 전달한다. Actions에서는 Secret 또는 Workload Identity Federation을 사용한다. 키 JSON이나 keystore 비밀번호를 저장소·채팅·로그에 넣지 않는다.
- `bundle exec fastlane android verify_access`: OAuth와 실제 앱 패키지 조회를 구분해 검사한다. 키 인증 성공만으로 앱 권한·업로드 준비 완료를 판단하지 않는다.
- 첫 수동 업로드로 이미 등록한 AAB를 다시 `draft`로 올리지 않는다. `bundle exec fastlane android sync_listing aab:/absolute/app.aab`으로 기존 트랙 버전의 문구·이미지·출시 노트만 동기화한다. 이 lane은 AAB를 재업로드하거나 출시 상태·rollout을 변경하지 않는다.
- `bundle exec fastlane android draft aab:/absolute/app.aab`: 내부 트랙 draft와 등록정보 업로드. draft는 테스트 사용자 배포나 심사 제출이 완료됐다는 의미가 아니다. Console에서 신고를 마친 뒤 테스트 릴리스를 게시한다.
- `bundle exec fastlane android promote version_code:NN from:internal to:production rollout:0.1`: 테스트한 특정 코드를 10% 프로덕션 출시로 승격. 사용자의 실제 출시 요청과 계정의 프로덕션 접근이 있을 때 실행한다. 동일 AAB를 다시 빌드하거나 업로드하지 않는다.
- 업로드 오류 또는 네트워크 끊김 뒤에는 Console/트랙 버전을 먼저 확인한다. 성공 여부가 불명확한 업로드·commit을 무한 재시도하지 않는다. 수정 릴리스는 새 versionCode로 배포한다. 이전 versionCode를 낮춰 롤백할 수 없다.

## 최신 요건을 확인할 공식 출처

- [대상 API](https://support.google.com/googleplay/android-developer/answer/11926878): 현재 휴대전화 신규/업데이트 제출은 API 36 이상.
- [16 KB 호환](https://developer.android.com/guide/practices/page-sizes): native ELF와 APK ZIP 정렬을 각각 검사. AGP만 올려도 기존 `.so`가 자동 재컴파일되지는 않는다. 문서와 Console의 적용 일정은 다음 릴리스에 다시 확인한다.
- [스토어 이미지](https://support.google.com/googleplay/android-developer/answer/9866151), [앱 설정/문자수](https://support.google.com/googleplay/android-developer/answer/9859152).
- [Play App Signing](https://support.google.com/googleplay/android-developer/answer/9842756).
- [심사 정보](https://support.google.com/googleplay/android-developer/answer/9859455), [데이터 보안](https://support.google.com/googleplay/android-developer/answer/10787469).
- [FGS 신고](https://support.google.com/googleplay/android-developer/answer/13392821).
- [외부 자체 업데이트 제한](https://support.google.com/googleplay/android-developer/answer/16559646): Play 배포판은 외부 APK 자체 업데이트를 사용하지 않는다.
- [개인 계정 테스트](https://support.google.com/googleplay/android-developer/answer/14151465).
- [API 설정](https://developers.google.com/android-publisher/getting_started), [fastlane](https://docs.fastlane.tools/actions/upload_to_play_store/).
