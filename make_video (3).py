"""
Fully free faceless TikTok video generator.
Gemini (free API) -> script | Pollinations (free) -> images | edge-tts (free) -> voice
FFmpeg (free) -> zoom motion + captions + final mp4
"""
import os, json, random, subprocess, time, pathlib, urllib.parse, requests

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
# Google renames/retires models often (2.0 is already dead). The script tries these in order.
MODELS = [m for m in [os.environ.get("GEMINI_MODEL"), "gemini-3.1-flash-lite", "gemini-flash-latest",
                      "gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"] if m]
# Natural-sounding "Multilingual" neural voices first; falls back down the list if one is unavailable.
VOICES = [v for v in [os.environ.get("TTS_VOICE"), "en-US-AndrewMultilingualNeural",
                      "en-US-BrianMultilingualNeural", "en-US-ChristopherNeural", "en-GB-RyanNeural"] if v]
RATE = os.environ.get("TTS_RATE", "-3%")     # slightly slower = calmer, more human
PITCH = os.environ.get("TTS_PITCH", "-2Hz")  # slightly lower = darker tone
MUSIC_DIR = pathlib.Path("music")            # optional: drop your own royalty-free .mp3 files here
MUSIC_VOLUME = os.environ.get("MUSIC_VOLUME", "0.22")
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
- Write like a calm, mysterious human storyteller: contractions, varied sentence length, natural pauses with commas and '...'. Never sound like a list or an encyclopedia.
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
        for i in range(2):
            try:
                r = requests.post(url, params={"key": GEMINI_KEY}, json=body, timeout=60)
            except requests.RequestException as e:
                last = f"{model}: {type(e).__name__}"
                print("Gemini request failed:", last)
                time.sleep(10)
                continue
            if r.status_code == 200:
                try:
                    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                except (KeyError, ValueError, IndexError):
                    break
            last = f"{model}: {r.status_code} {r.text[:200]}"
            print("Gemini error:", last)
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
    for v in VOICES:
        for extra in ([f"--rate={RATE}", f"--pitch={PITCH}"], []):  # second try: no tuning
            r = subprocess.run(["edge-tts", "--voice", v, *extra, "--text", text,
                                "--write-media", str(mp3), "--write-subtitles", str(vtt)])
            if r.returncode == 0 and mp3.exists() and mp3.stat().st_size > 1000:
                return
    raise RuntimeError("Text-to-speech failed for every voice")


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


def make_drone(d, out):
    """Generate a dark ambient drone with FFmpeg only: free, copyright-safe, no downloads."""
    d = f"{d:.2f}"
    tone = ("0.35*sin(2*PI*55*t)+0.25*sin(2*PI*82.4*t)"
            "+0.2*sin(2*PI*110.3*t)*(0.6+0.4*sin(2*PI*0.1*t))"
            "+0.12*sin(2*PI*164.8*t)*(0.5+0.5*sin(2*PI*0.07*t))")
    fade_out_at = max(float(d) - 3, 0)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"aevalsrc={tone}:d={d}:s=44100",
                    "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.3:d={d}:sample_rate=44100",
                    "-filter_complex",
                    "[0:a]lowpass=f=450[a0];[1:a]lowpass=f=300,volume=0.5[a1];"
                    "[a0][a1]amix=inputs=2:duration=longest,"
                    f"afade=t=in:d=2,afade=t=out:st={fade_out_at:.2f}:d=3,volume=2[m]",
                    "-map", "[m]", str(out)], check=True)


def add_music(video_in, video_out):
    d = duration(video_in)
    tracks = sorted(MUSIC_DIR.glob("*.mp3")) if MUSIC_DIR.exists() else []
    if tracks:  # your own royalty-free tracks, looped and faded to fit
        music_in = ["-stream_loop", "-1", "-i", str(random.choice(tracks))]
        prep = f"[1:a]aresample=44100,afade=t=out:st={max(d - 3, 0):.2f}:d=3,volume={MUSIC_VOLUME}[m]"
    else:       # built-in dark drone
        drone = OUT / "drone.wav"
        make_drone(d, drone)
        music_in = ["-i", str(drone)]
        prep = f"[1:a]aresample=44100,volume={MUSIC_VOLUME}[m]"
    graph = (f"[0:a]aresample=44100,volume=1.6[v];{prep};"
             "[v][m]amix=inputs=2:duration=first:dropout_transition=0[a]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_in), *music_in,
                    "-filter_complex", graph, "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{d:.2f}", str(video_out)], check=True)


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
    raw = OUT / "raw.mp4"
    final = OUT / "final.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(raw)], check=True)
    try:
        add_music(raw, final)
    except Exception as e:  # never lose a video because of the music step
        print("Music step failed, using voice only:", e)
        raw.replace(final)
    caption = f"{data['title']}\n\n{data['caption']}\n\n{' '.join(data['hashtags'])} #fyp #darkfacts"
    (OUT / "caption.txt").write_text(caption)
    with USED.open("a") as f:
        f.write(data["topic"] + "\n")
    send_telegram(final, caption)
    print("DONE:", data["topic"])


if __name__ == "__main__":
    main()
