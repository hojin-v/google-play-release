#!/usr/bin/env python3
"""Collect app-specific Play facts; never submit forms or choose unknown answers."""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def question(key, title, guide, choices=None, *, kind="choice", depends=None, business=False):
    return {"id": key, "title": title, "guide": guide, "kind": kind,
            "choices": [{"value": value, "label": label} for value, label in (choices or [])],
            "depends": depends, "business": business}


YES_NO = [("no", "없음 / 아니요"), ("yes", "있음 / 예")]
QUESTIONS = [
    question("countries", "어느 국가에 배포하나요?", "국가 코드를 쉼표로 입력합니다. 예: KR 또는 KR,US. 첫 앱의 지역을 다른 앱에 복사하지 않습니다.", kind="countries", business=True),
    question("pricing", "앱 다운로드 가격은 어떻게 하나요?", "무료 앱은 출시 후 유료 앱으로 전환할 수 없습니다. 인앱 결제 여부는 별도입니다.", [("free", "무료"), ("paid", "유료")], business=True),
    question("target_audience", "어떤 연령대를 대상으로 하나요?", "쉼표로 실제 대상 연령대를 입력합니다: 0-5,6-8,9-12,13-15,16-17,18+. 콘텐츠 등급과 별도이며 아동 대상이면 추가 정책이 적용됩니다.", kind="ages", business=True),
    question("app_type", "앱 유형은 무엇인가요?", "콘텐츠 등급 설문의 카테고리 선택에도 사용합니다. 실제 IARC 등급은 Console 설문 결과로 받아야 합니다.", [("utility", "일반 앱 / 도구"), ("game", "게임 / 베팅"), ("social", "소셜 / 커뮤니케이션")]),
    question("ads", "앱에 광고가 있나요?", "제3자 광고 SDK, 배너, 전면 광고, 보상형 광고 등을 포함합니다.", YES_NO),
    question("ad_id", "광고 ID를 사용하나요?", "광고 표시 여부와 별도로 SDK 및 최종 manifest의 AD_ID 권한과 실제 사용을 확인합니다.", YES_NO),
    question("purchases", "앱 안에서 디지털 상품·구독을 구매하나요?", "다운로드 가격과 별도로 인앱 결제 및 유료 콘텐츠 접근을 확인합니다. 금융 앱 선언과 같은 뜻이 아닙니다.", YES_NO),
    question("accounts", "앱에서 온라인 계정을 만들 수 있나요?", "앱 안에서 직접 만들거나 외부 웹페이지를 통해 만드는 계정을 포함합니다. 계정이 있으면 삭제 경로와 데이터 보안 세부 답변을 확인해야 합니다.", YES_NO),
    question("account_deletion_url", "사용자가 계정 삭제를 요청할 공개 URL은 무엇인가요?", "실제 삭제 또는 삭제 요청 절차를 안내하는 공개 URL을 입력합니다. 앱 내부 삭제 경로도 별도로 확인합니다.", kind="url", depends=("accounts", ["yes"])),
    question("access", "심사자가 기능에 접근하기 위한 조건이 있나요?", "로그인, 유료 구독, 지역 제한, 일회용 코드 또는 특정 기기 설정이 필요하면 제한 있음입니다.", [("open", "조건 없이 접근 가능"), ("restricted", "로그인·결제·코드·기기 설정 등 필요")]),
    question("access_instructions", "어떤 조건과 설정 절차가 필요한가요?", "영문 심사 안내 또는 공개 설명 URL을 입력합니다. 비밀번호·토큰은 이 Git 저장 파일에 넣지 말고 Console의 전용 입력란에 보관합니다.", kind="text", depends=("access", ["restricted"])),
    question("data", "사용자 데이터를 수집하거나 제3자와 공유하나요?", "앱과 모든 SDK를 포함합니다. 기기 밖 전송과 제3자 제공을 확인하며 로컬 처리와 구분합니다. 모르면 건너뛰고 조사합니다.", [("none", "수집·공유 없음"), ("collected", "수집함"), ("shared", "공유함"), ("both", "수집 및 공유함")]),
    question("data_details", "어떤 데이터를 어떤 목적으로 처리하나요?", "데이터 유형, SDK/수신자, 필수·선택 여부, 암호화, 보관·삭제, 계정 생성 여부를 설명합니다. 이 메모를 근거로 Console 데이터 보안의 세부 질문에 답해야 합니다.", kind="text", depends=("data", ["collected", "shared", "both"])),
    question("sensitive_content", "폭력·성적 표현·도박·연령 제한 상품 등 등급 관련 콘텐츠가 있나요?", "스토어 소개, 앱에 포함된 자료와 온라인 콘텐츠를 확인합니다. '없음'을 선택해도 실제 IARC 설문은 별도로 완료합니다.", YES_NO),
    question("content_details", "어떤 등급 관련 콘텐츠가 있나요?", "종류와 강도, 접근 조건, 사용자 제작 콘텐츠 여부를 설명합니다. 등급을 임의로 정하지 않고 실제 IARC 질문에 답합니다.", kind="text", depends=("sensitive_content", ["yes"])),
    question("health", "건강·의료·피트니스 기능이 있나요?", "모든 앱에 건강 선언이 요구될 수 있습니다. 기능이 없으면 '없음', 있으면 실제 기능과 지역별 증빙을 추가합니다.", YES_NO),
    question("health_details", "어떤 건강 기능을 제공하나요?", "운동·수면·영양·의료·진료 등 실제 기능과 해당 지역의 문서/등록 여부를 적습니다. 해당 Console 설문은 별도 완료해야 합니다.", kind="text", depends=("health", ["yes"])),
    question("finance", "금융·결제·대출·암호화폐 기능이 있나요?", "단순히 유료 앱이라는 뜻이 아닙니다. 앱이 제공하는 실제 금융 기능을 기준으로 답합니다.", YES_NO),
    question("finance_details", "어떤 금융 기능을 제공하나요?", "기능, 제공 국가, 필요한 등록·라이선스 및 증빙 여부를 설명합니다. Console에 추가 문서가 필요할 수 있습니다.", kind="text", depends=("finance", ["yes"])),
    question("government", "정부가 개발했거나 정부를 대신해 제공하나요?", "정부 기능이 없는 일반 앱이면 '없음'입니다. 공공 데이터를 사용하는 것과 정부 앱 여부를 구분합니다.", YES_NO),
    question("government_details", "어떤 정부 기관과 관계가 있나요?", "개발·위탁 관계와 공식 증빙을 설명합니다. 관계를 추측해서 기입하지 않습니다.", kind="text", depends=("government", ["yes"])),
    question("foreground_service", "포그라운드 서비스를 사용하나요?", "최종 AAB의 FOREGROUND_SERVICE_* 권한과 서비스 유형을 확인합니다. 사용하는 유형별로 용도·중단 영향·실제 시연이 필요할 수 있습니다.", YES_NO),
    question("fgs_details", "서비스 유형, 사용자 시작 동작과 중단 영향을 설명해 주세요.", "최종 manifest의 실제 서비스 유형과, 앱을 벗어나도 즉시 지속해야 하는 이유 및 종료 조건을 적습니다.", kind="text", depends=("foreground_service", ["yes"])),
    question("fgs_video_url", "FGS 실제 기능 영상의 공개 URL은 무엇인가요?", "심사자가 로그인 없이 재생할 수 있어야 합니다. 실제로 검증하지 않은 기능을 영상의 증거로 주장하지 않습니다.", kind="url", depends=("foreground_service", ["yes"])),
    question("privacy_policy_url", "앱의 공개 개인정보처리방침 URL은 무엇인가요?", "로그인·지역 제한 없이 열리는 HTTPS 문서여야 합니다. 앱 및 데이터 보안 답변과 일치하는지 별도 검증합니다.", kind="url"),
]
BY_ID = {q["id"]: q for q in QUESTIONS}
SOURCES = ("user", "operator", "code", "console")
AGE_GROUPS = {"0-5", "6-8", "9-12", "13-15", "16-17", "18+"}


def normalize(q, value):
    if isinstance(value, list) and q["kind"] in ("countries", "ages"):
        if not all(isinstance(v, str) for v in value):
            raise ValueError(f'{q["id"]}: 문자열 목록이 필요합니다')
        value = ",".join(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{q["id"]}: 답변이 비어 있습니다')
    value = value.strip()
    if q["kind"] == "choice" and value not in {o["value"] for o in q["choices"]}:
        raise ValueError(f'{q["id"]}: 표시된 선택지의 value를 사용하세요')
    if q["kind"] in ("countries", "ages"):
        values = list(dict.fromkeys(v.strip() for v in value.split(",")))
        if q["kind"] == "countries":
            values = [v.upper() for v in values]
            if not all(re.fullmatch(r"[A-Z]{2}", v) for v in values):
                raise ValueError("countries: 두 글자 국가 코드를 입력하세요")
        elif not set(values) <= AGE_GROUPS:
            raise ValueError("target_audience: 표시된 연령 구간을 사용하세요")
        return list(dict.fromkeys(values))
    if q["kind"] == "url":
        url = urlparse(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError(f'{q["id"]}: 인증정보가 없는 공개 HTTPS URL이 필요합니다')
    return value


def active(q, answers):
    return not q["depends"] or answers.get(q["depends"][0], {}).get("value") in q["depends"][1]


def pending(state):
    return [q for q in QUESTIONS if active(q, state["answers"]) and q["id"] not in state["answers"]]


def apply_answers(state, values, source):
    """Validate the entire batch before modifying state."""
    if source not in SOURCES:
        raise ValueError("알 수 없는 답변 출처")
    updates = {}
    for key, value in values.items():
        if key not in BY_ID:
            raise ValueError(f"알 수 없는 질문: {key}")
        q = BY_ID[key]
        if q["business"] and source == "code":
            raise ValueError(f"{key}: 코드로 사업상의 선택을 결정할 수 없습니다")
        updates[key] = {"value": normalize(q, value), "source": source,
                        "answered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    state["answers"].update(updates)


def load_state(root):
    config = json.loads((root / "play/release.json").read_text())
    path = root / "play/declarations.json"
    state = json.loads(path.read_text()) if path.exists() else {
        "schema_version": 1, "package_name": config["package_name"], "answers": {}}
    if state.get("schema_version") != 1 or state.get("package_name") != config["package_name"]:
        raise ValueError("질문 답변 파일의 버전 또는 패키지가 프로젝트와 다릅니다")
    if not isinstance(state.get("answers"), dict):
        raise ValueError("잘못된 answers 형식")
    for key, record in state["answers"].items():
        if key not in BY_ID or not isinstance(record, dict) or record.get("source") not in SOURCES:
            raise ValueError(f"유효하지 않은 답변 기록: {key}")
        record["value"] = normalize(BY_ID[key], record.get("value"))
        if BY_ID[key]["business"] and record["source"] == "code":
            raise ValueError(f"{key}: 사업상 선택에는 사용자 또는 Console 근거가 필요합니다")
    return state


def save_state(root, state):
    path = root / "play/declarations.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def report(state):
    followup = ["최종 AAB·SDK·데이터 흐름 검토", "실제 Console IARC 설문 및 등급 결과 확인",
                "대상 연령·데이터 보안·광고·액세스 등 실제 Console 설문 완료",
                "공개 방침·스토어 자료·가격·국가 확인", "계정별 테스트 조건 및 심사·출시 상태 확인"]
    answers = state["answers"]
    for key, label in [("health", "건강 기능과 지역별 증빙"), ("finance", "금융 기능과 국가별 증빙"),
                       ("government", "정부 관계 증빙"), ("foreground_service", "FGS 유형별 신고 및 실제 영상")]:
        if answers.get(key, {}).get("value") == "yes":
            followup.append(label)
    if any(a != "18+" for a in answers.get("target_audience", {}).get("value", [])):
        followup.append("선택한 아동·청소년 연령에 따른 콘텐츠 및 Families 적용 여부 확인")
    return {"package_name": state["package_name"], "facts_complete": not pending(state),
            "pending_questions": pending(state), "console_followup": followup,
            "note": "앱별 사실을 정리하는 도구입니다. Console 설문 완료·정책 승인·출시 완료를 의미하지 않습니다."}


def interview(root, state, input_fn=input, output_fn=print):
    if not sys.stdin.isatty() and input_fn is input:
        raise ValueError("대화형 interview는 터미널이 필요합니다. questions --json 및 answer --file을 사용할 수 있습니다")
    skipped = set()
    while todo := [q for q in pending(state) if q["id"] not in skipped]:
        q = todo[0]
        output_fn(f'\n[{q["id"]}] {q["title"]}\n{q["guide"]}')
        for i, option in enumerate(q["choices"], 1):
            output_fn(f'  {i}. {option["label"]} ({option["value"]})')
        raw = input_fn("답변 (s: 미정으로 남김, q: 저장 후 종료): ").strip()
        if raw == "q":
            break
        if raw == "s":
            skipped.add(q["id"])
            continue
        if q["choices"] and raw.isdigit() and 1 <= int(raw) <= len(q["choices"]):
            raw = q["choices"][int(raw) - 1]["value"]
        try:
            apply_answers(state, {q["id"]: raw}, "operator")
            save_state(root, state)
        except ValueError as error:
            output_fn(str(error))
    return report(state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("questions").add_argument("--json", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.add_argument("--require-complete", action="store_true", help="fail if any applicable fact is unanswered")
    sub.add_parser("interview")
    answer = sub.add_parser("answer")
    group = answer.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", choices=BY_ID)
    group.add_argument("--file", type=Path, help="JSON object mapping question IDs to values")
    answer.add_argument("--value")
    answer.add_argument("--source", choices=SOURCES, default="operator")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    state = load_state(root)
    if args.command == "answer":
        if args.file and args.value is not None:
            parser.error("--value는 --id와 함께 사용합니다")
        values = json.loads(args.file.read_text()) if args.file else {args.id: args.value}
        if not isinstance(values, dict) or not values:
            raise ValueError("비어 있지 않은 질문 ID/답변 JSON 객체가 필요합니다")
        apply_answers(state, values, args.source)
        save_state(root, state)
    result = interview(root, state) if args.command == "interview" else report(state)
    if getattr(args, "json", False) or args.command == "answer":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f'{result["package_name"]}: 미정 질문 {len(result["pending_questions"])}개')
        for q in result["pending_questions"]:
            print(f'\n[{q["id"]}] {q["title"]}\n{q["guide"]}')
            for option in q["choices"]:
                print(f'  {option["value"]}: {option["label"]}')
        print("\nConsole에서 별도 확인할 항목:")
        for item in result["console_followup"]:
            print(f"- {item}")
        print(result["note"])
    return 2 if getattr(args, "require_complete", False) and not result["facts_complete"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, EOFError, KeyboardInterrupt) as error:
        print(f"질문 처리 중단: {error}", file=sys.stderr)
        sys.exit(1)
