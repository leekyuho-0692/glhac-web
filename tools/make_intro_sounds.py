# -*- coding: utf-8 -*-
"""인트로 효과음을 만든다 — intro/gong.mp3, intro/door-creak2.mp3.

소리를 손으로 만들어 두면 나중에 아무도 고칠 수 없다. 여기에 만드는 법을
남긴다. 실행하면 배포된 것과 **같은 바이트**가 나온다(난수 씨앗 고정).

    python tools/make_intro_sounds.py [--check]

  --check  다시 만들어 보고 기존 파일과 같은지만 확인한다(덮어쓰지 않는다).

가믈란(gamelan.mp3)·중립음(tadum.mp3)은 이 스크립트가 만든 것이 아니라
이전에 만들어 둔 파일을 그대로 쓴다.
"""
import argparse
import hashlib
import os
import struct
import subprocess
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTRO = os.path.join(ROOT, "intro")
SR = 44100

# 문 소리 원본 — ElevenLabs 로 받은 7.05초짜리. 저장소에는 넣지 않는다(용량·출처).
DOOR_SRC = os.path.expanduser(
    "~/Downloads/ElevenLabs_Creaking_door_opening_slowly_in_an_old_house,"
    "_eerie_ambiance.mp3")


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(v * 32767)) for v in x))


def make_gong(out_wav):
    """징 — 한 번 길게.

    징 소리를 징답게 만드는 건 세 가지다.
      ① 낮은 기음(92Hz)과 **배음이 아닌** 부분음 — 정수배가 아니어야 금속 공 소리가 난다
      ② 맥놀이 — 아주 가까운 두 주파수가 어긋나며 소리가 울렁인다. 사실상 이것이 징이다
      ③ 때린 직후보다 조금 뒤에 피어오르는 고음(비선형 공진) — 그래서 '퍼지는' 느낌이 난다
    """
    rng = np.random.default_rng(7)          # 고정 — 매번 같은 소리가 나와야 한다
    dur = 3.6
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)

    #                주파수  세기   감쇠  맥놀이 어긋남(Hz)
    partials = [(92, 1.00, 0.55, 2.6), (151, 0.42, 0.8, 3.9),
                (248, 0.30, 1.1, 5.1), (372, 0.20, 1.5, 6.3),
                (505, 0.14, 2.0, 7.7), (741, 0.09, 2.7, 9.2),
                (1063, 0.05, 3.4, 11.4)]
    for f, a, d, beat in partials:
        env = np.exp(-t * d)
        out += a * env * (np.sin(2 * np.pi * f * t)
                          + 0.85 * np.sin(2 * np.pi * (f + beat) * t + 0.7))

    bloom = np.zeros(n)                      # ③ 나중에 피어오르는 고음
    for f, a in ((1480, .10), (1970, .08), (2630, .05), (3310, .035)):
        bloom += a * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
    out += bloom * (t / 0.35 * np.exp(1 - t / 0.35)) * np.exp(-t * 1.5)

    out += rng.normal(0, 1, n) * np.exp(-t * 90) * 0.28      # 때리는 순간

    out *= np.minimum(1, t / 0.004)
    out /= np.max(np.abs(out)) + 1e-9
    out *= 0.85
    f = int(0.9 * SR)
    out[-f:] *= np.cos(np.linspace(0, np.pi / 2, f)) ** 1.5  # 자연스러운 소멸
    write_wav(out_wav, out)


def encode(src_wav, dst_mp3, bitrate):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src_wav,
                    "-c:a", "libmp3lame", "-b:a", bitrate, dst_mp3], check=True)


def make_door(dst_mp3):
    """문 열리는 끼익 — 원본에서 마찰음이 진한 두 구간을 이어 붙인다.

    원본 7.05초 중 실제로 '끼익' 하는 곳은 1.0~3.0초와 4.0~5.3초 두 군데다.
    그대로 이어 붙이면 자른 자리가 들리므로 0.25초 겹쳐 넘긴다.
    """
    if not os.path.exists(DOOR_SRC):
        print("  건너뜀 — 원본이 없다: %s" % DOOR_SRC)
        return False
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-ss", "1.00", "-t", "2.15", "-i", DOOR_SRC,
        "-ss", "4.05", "-t", "1.30", "-i", DOOR_SRC,
        "-filter_complex",
        "[0:a]afade=t=in:st=0:d=0.05[a];[1:a]afade=t=out:st=0.85:d=0.45[b];"
        "[a][b]acrossfade=d=0.25:c1=tri:c2=tri,loudnorm=I=-18:TP=-2:LRA=11[o]",
        "-map", "[o]", "-ac", "1", "-ar", "44100",
        "-c:a", "libmp3lame", "-b:a", "96k", dst_mp3], check=True)
    return True


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="다시 만들어 기존 파일과 같은지만 확인한다")
    args = ap.parse_args()

    tmp = os.path.join(INTRO, ".make_tmp")
    os.makedirs(tmp, exist_ok=True)
    made = {}

    gw = os.path.join(tmp, "gong.wav")
    make_gong(gw)
    encode(gw, os.path.join(tmp, "gong.mp3"), "112k")
    made["gong.mp3"] = os.path.join(tmp, "gong.mp3")

    if make_door(os.path.join(tmp, "door-creak2.mp3")):
        made["door-creak2.mp3"] = os.path.join(tmp, "door-creak2.mp3")

    bad = 0
    for name, new in made.items():
        cur = os.path.join(INTRO, name)
        if args.check:
            if not os.path.exists(cur):
                print("  %-18s 기존 파일 없음" % name); bad += 1; continue
            same = sha(cur) == sha(new)
            print("  %-18s %s  (기존 %s · 새로 %s)" %
                  (name, "같음" if same else "다름", sha(cur), sha(new)))
            if not same:
                bad += 1
        else:
            os.replace(new, cur)
            print("  %-18s 갱신 %s" % (name, sha(cur)))

    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
