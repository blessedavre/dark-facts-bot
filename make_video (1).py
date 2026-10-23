"""
Fully free faceless TikTok video generator.
Gemini (free API) -> script | Pollinations (free) -> images | edge-tts (free) -> voice
FFmpeg (free) -> zoom motion + captions + final mp4
"""
import os, json, random, subprocess, time, pathlib, urllib.parse, requests

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
# Google renames/retires models often (2.0 is already dead). The script tries these in order.
MODELS = [m for m in [os.environ.get("GEMINI_MODEL"), "gemini-flash-latest", "gemini-3.1-flash-lite",
                      "gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"] if m]
VOICE = os.environ.get("TTS_VOICE", "en-US-GuyNeural")
NICHE = "Deep Dark Facts: creepy, mind-blowing facts about the deep ocean, space, and strange animals"
STYLE = ("dark cinematic digital painting, moody lighting, deep blues and blacks, "
         "highly detailed, vertical composition, no people, no text")
W, H = 1080, 1920
OUT = pathlib.Path("out")
OUT.mkdir(exist_ok=True)
USED = pathlib.Path("used_topics.txt")

PROMPT = """You write viral faceless TikTok scripts. Niche: {niche}.
Topics already used (never repeat or closely overlap):
{used}

Pick ONE new, specific, surprising topic and write a 25-35 second script (70-90 words total).
Rules:
- Scene 1 narration is a shocking hook under 12 words.
- Short punchy sentences, dark mysterious tone, simple words.
- Final scene ends with a question or cliffhanger that makes people comment.
- Image prompts: ONLY animals, ocean, space, landscapes, objects. NEVER humans or faces.
- 6 to 8 scenes, each narration 1-2 short sentences.
Return JSON only:
{{"topic": "...", "title": "...", "caption": "...", "hashtags": ["#..."],
  "scenes": [{{"narration": "...", "image_prompt": "..."}}]}}"""


def llm(prompt):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.1}}
    last = None
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for i in range(3):
            r = requests.post(url, params={"key": GEMINI_KEY}, json=body, timeout=90)
            if r.status_code == 200:
                try:
                    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                except (KeyError, ValueError):
                    break
            last = f"{model}: {r.status_code} {r.text[:200]}"
            if r.status_code in (404, 400, 403):
                break  # model gone or not allowed: try the next one
            time.sleep(15 * (i + 1))
    raise RuntimeError(f"All Gemini models failed. Last error: {last}")


def make_image(prompt, path, seed):
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(f"{prompt}, {STYLE}")
    for i in range(6):
        try:
            r = requests.get(url, params={"width": W, "height": H, "nologo": "true", "seed": seed}, timeout=120)
            if r.status_code == 200 and len(r.content) > 10000:
                path.write_bytes(r.content)
                time.sleep(16)  # anonymous tier allows ~1 request / 15 s
                return
        except requests.RequestException:
            pass
        time.sleep(16 * (i + 1))
    raise RuntimeError(f"image failed: {prompt}")


def tts(text, mp3, vtt):
    subprocess.run(["edge-tts", "--voice", VOICE, "--rate=+8%", "--text", text,
                    "--write-media", str(mp3), "--write-subtitles", str(vtt)], check=True)


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", str(path)])
    return float(out)


def make_clip(img, mp3, vtt, out, zoom_in):
    d = duration(mp3) + 0.25
    frames = int(d * 30)
    z = "min(zoom+0.0007,1.25)" if zoom_in else "if(eq(on,0),1.25,max(zoom-0.0007,1.0))"
    style = "FontName=Arial,FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=3,Alignment=2,MarginV=60"
    vf = (f"scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=30,"
          f"subtitles={vtt}:force_style='{style}',format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(img), "-i", str(mp3),
                    "-vf", vf, "-af", "apad", "-t", f"{d:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                    "-c:a", "aac", "-r", "30", str(out)], check=True)


def send_telegram(video, text):
    token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if not (token and chat):
        return
    with open(video, "rb") as f:
        requests.post(f"https://api.telegram.org/bot{token}/sendVideo",
                      data={"chat_id": chat, "caption": text[:1000]}, files={"video": f}, timeout=300)


def main():
    used = USED.read_text().splitlines()[-300:] if USED.exists() else []
    data = llm(PROMPT.format(niche=NICHE, used="\n".join(used) or "(none yet)"))
    scenes = data["scenes"]
    clips = []
    for i, s in enumerate(scenes):
        img, mp3, vtt, clip = OUT / f"s{i}.jpg", OUT / f"s{i}.mp3", OUT / f"s{i}.vtt", OUT / f"s{i}.mp4"
        make_image(s["image_prompt"], img, random.randint(1, 10**6))
        tts(s["narration"], mp3, vtt)
        make_clip(img, mp3, vtt, clip, zoom_in=(i % 2 == 0))
        clips.append(clip)
    lst = OUT / "list.txt"
    lst.write_text("\n".join(f"file '{c.resolve()}'" for c in clips))
    final = OUT / "final.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(final)], check=True)
    caption = f"{data['title']}\n\n{data['caption']}\n\n{' '.join(data['hashtags'])} #fyp #darkfacts"
    (OUT / "caption.txt").write_text(caption)
    with USED.open("a") as f:
        f.write(data["topic"] + "\n")
    send_telegram(final, caption)
    print("DONE:", data["topic"])


if __name__ == "__main__":
    main()
