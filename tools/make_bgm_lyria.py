"""BGMを Google Lyria 3.5（Gemini API）で1曲作り assets/bgm/ に置く。

- 1曲 約3分・$0.08（無料枠なし・API従量）。本社ルールの例外②（Claudeにできない仕事）。
- main.py は assets/bgm/ の最初の mp3/wav をループして BGM_VOLUME で敷く。
- assets/bgm/*.mp3 は .gitignore 対象＝別PCでは再実行して作る。
- 呼び出しは REST（google-genai 1.53 に interactions が無いため）。使用履歴は親子両方の llm_usage.jsonl へ。

使い方: python tools/make_bgm_lyria.py
"""
import base64, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"D:\AutoSystem\PythonSystem")
load_dotenv(ROOT / "_shared" / "secrets" / ".env", override=False)
key = os.environ["GEMINI_API_KEY"]
prompt = ("A 3-minute calm, emotional background score for a Japanese human drama narration. "
          "Soft solo piano with gentle strings pad, slow tempo around 70 BPM, warm and slightly melancholic, "
          "hopeful undertone. Steady dynamics without sudden climaxes, so it sits quietly under a narrator's voice. "
          "Ends in a way that loops smoothly back to the beginning. Instrumental only, no vocals.")
body = {"model": "lyria-3.5", "input": prompt}
req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/interactions",
    data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"})
t = time.time()
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        res = json.loads(r.read())
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:800]); sys.exit(1)
el = time.time() - t
out = ROOT / "3_drama-video-generator" / "assets" / "bgm" / "drama_piano_lyria35.mp3"
n = 0; texts = []
for s in res.get("steps", []):
    for c in s.get("content", []) or []:
        if c.get("type") == "audio" and c.get("data"):
            out.write_bytes(base64.b64decode(c["data"])); n += 1
        elif c.get("type") == "text":
            texts.append(c.get("text", ""))
meta = {k: v for k, v in res.items() if k != "steps"}
print("elapsed", round(el,1), "audio_blocks", n, "meta", json.dumps(meta, ensure_ascii=False)[:800])
print("text", "\n".join(texts)[:800])
rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "provider": "gemini", "model": "lyria-3.5",
       "project": "3_drama-video-generator", "purpose": "BGM 1曲の小口実測（18番申し送り）",
       "usage": meta.get("usage", {}), "cost_usd_list_price": 0.08}
for p in [ROOT/"_shared"/"usage"/"llm_usage.jsonl", ROOT/"3_drama-video-generator"/"llm_usage.jsonl"]:
    with p.open("a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False)+"\n")
