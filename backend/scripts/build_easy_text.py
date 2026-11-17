"""정책 패널 「쉬운 말로 보기」 미리 만들기 → backend/data/easy_text.json

로컬 Qwen3-VL-4B-Instruct(글만, greedy)가 지원대상·선정기준 원문의 행정용어를 쉬운 말로 바꿈.
숫자 검사: 쉬운 말 안의 모든 숫자(금액·나이·기간·비율 등, 쉼표 뺀 숫자+단위)가 원문에 그대로 있어야 함.
내용 검사: 같은 모델이 원문과 쉬운 말을 비교해 다른·없는 내용이 있다고 보면(P(예) ≥ 0.5) 숨김. 둘 다 통과해야 ok=true → 화면에 보임.
원문은 화면에 항상 함께 보임(쉬운 말은 보조).

    python backend/scripts/build_easy_text.py   (GPU — API 서버를 내린 뒤)
"""
import json, re, sys, time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "ai/experiments/vlm_model")]
from lora_make_data import Gen

FIELDS = {"targetDetail": "지원대상", "criteria": "선정기준"}
PROMPT = """다음은 복지 정책 「{name}」의 {field} 원문입니다.

{text}

원문의 항목(○, -, · 로 시작하는 줄)을 순서대로, 항목마다 한 문장씩 쉬운 말로 바꾸세요.
- 조건을 나타내는 말(이상, 이하, 미만, 모두, 또는, 제외, 단)은 뜻이 바뀌지 않게 그대로 지키세요. 항목을 합치거나 빼지 마세요.
- 행정용어(예: 소득인정액, 차상위, 기준 중위소득)는 쉬운 말로 짧게 풀이하세요.
- 금액·나이·기간·비율 같은 숫자는 원문 그대로 쓰고, 계산하거나 새 숫자를 만들지 마세요.
- 원문에 없는 설명·이유·평가는 더하지 마세요. 바꾼 문장만 쓰세요."""
NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(만\s*원|천\s*원|억|원|세|살|%|개월|년|일|시간|배|명|회|급|점)?")


def numbers(t):
    out = set()
    for m in NUM.finditer(t or ""):
        n = m.group(1).replace(",", "")
        unit = re.sub(r"\s", "", m.group(2) or "").replace("살", "세")
        out.add((n, unit))
    return out


def check(orig, easy):
    o = numbers(orig); e = numbers(easy)
    o_n = {n for n, _ in o}
    bad = [f"{n}{u}" for n, u in e if (n, u) not in o and not (u == "" and n in o_n)]
    return not bad, bad


VERIFY = """[원문]
{src}

[쉬운 설명]
{easy}

쉬운 설명에 원문과 다르거나, 원문에 없는 내용이 하나라도 있습니까? 예 또는 아니오로만 답하세요."""


def p_yes(g, text):
    tok = g.proc.tokenizer
    yes, no = tok.encode("예", add_special_tokens=False)[0], tok.encode("아니오", add_special_tokens=False)[0]
    msgs = [[{"role": "user", "content": [{"type": "text", "text": text}]}]]
    x = g.proc(text=g.proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False), return_tensors="pt").to("cuda")
    with torch.no_grad():
        lg = g.model(**x).logits[0, -1].float()
    return float(torch.softmax(torch.stack([lg[yes], lg[no]]), 0)[0])


LINE_PROMPT = """다음은 복지 정책 「{name}」의 {field} 중 한 줄입니다.

{line}

이 한 줄을 어르신도 이해할 수 있는 쉬운 말 한 문장으로 바꾸세요.
- 이상·이하·미만·모두·또는·제외·단 같은 조건의 뜻을 그대로 지키세요.
- 숫자는 원문 그대로 쓰고, 원문에 없는 내용은 더하지 마세요.
- 행정용어는 쉬운 말로 바꾸거나 괄호로 짧게 풀이하세요. 문장만 쓰세요."""


def split_lines(src):
    """○ - · ㅇ ※ ① 등으로 시작하는 항목 단위로 나눔(줄바꿈 기준). 너무 짧은 머리말 줄(「○ 아동 연령 기준」 등)은 다음 줄에 붙임."""
    lines = [l.strip() for l in src.replace("\r", "\n").split("\n") if l.strip()]
    out, head = [], ""
    for l in lines:
        body = re.sub(r"^[\s○ㅇ◦•\-·※*]+", "", l)
        if len(body) <= 14 and not re.search(r"\d", body):
            head = body; continue
        out.append((head + ": " if head else "") + body); head = ""
    return out


def main():
    pols = json.loads((ROOT / "backend/data/policies.json").read_text())
    g = Gen()
    out = {}
    for p in pols:
        out[p["policyId"]] = {}
        for f, label in FIELDS.items():
            src = (p.get(f) or "").strip()
            if not src:
                continue
            items = split_lines(src)[:30]   # 항목마다 따로 쉬운 말 한 문장 (합치거나 조건을 바꾸는 실수를 줄임)
            msgs = [[{"role": "user", "content": [{"type": "text", "text": LINE_PROMPT.format(name=p["name"], field=label, line=it)}]}] for it in items]
            outs = []
            for i in range(0, len(msgs), 8):
                outs += g(msgs[i:i + 8], max_new=120)
            easy = "\n".join("· " + o.strip().splitlines()[0].strip() for o in outs if o.strip())
            num_ok, bad = check(src, easy)
            p_diff = p_yes(g, VERIFY.format(src=src[:1500], easy=easy))   # 내용 검사: 원문과 다른·없는 내용이 있다고 보면 숨김
            ok = num_ok and p_diff < 0.5
            out[p["policyId"]][f] = {"easy": easy, "ok": ok, "mismatch": bad, "p_content_diff": round(p_diff, 3), "source_chars": len(src)}
            print(p["name"], label, "통과" if ok else f"숨김(숫자 {bad or '일치'}, 내용 다름 확률 {p_diff:.2f})", flush=True)
    meta = {"model": "Qwen/Qwen3-VL-4B-Instruct", "generatedAt": time.strftime("%Y-%m-%d %H:%M"),
            "rule": "쉬운 말의 숫자가 모두 원문에 그대로 있고, 같은 모델이 원문과 비교해 다른·없는 내용이 없다고 볼 때(P(예)<0.5)만 표시(ok). 원문은 항상 함께 표시."}
    (ROOT / "backend/data/easy_text.json").write_text(json.dumps({"meta": meta, "policies": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→ backend/data/easy_text.json")


if __name__ == "__main__":
    main()
