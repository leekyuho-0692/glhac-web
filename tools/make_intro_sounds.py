# -*- coding: utf-8 -*-
"""인트로 효과음을 만든다 — 징·가믈란·중립음·문 열리는 소리.

소리를 손으로 만들어 두면 나중에 아무도 고칠 수 없다. 여기에 만드는 법을 남긴다.

    python tools/make_intro_sounds.py           # 확인만 한다(기본)
    python tools/make_intro_sounds.py --write   # intro/ 를 덮어쓴다

기본이 '확인'인 이유: 지금 배포된 소리를 실수로 바꾸지 않기 위해서다.

재현되는 것과 아닌 것
  · gong.mp3 · door-creak2.mp3 — 배포된 것과 **바이트까지 같다**(난수 씨앗 고정).
  · gamelan.mp3 · tadum.mp3   — 원래 만든 코드가 남지 않아, 기존 파일을 분석해
    특성(기음·부분음·타격 시점·대역 비율)을 뽑아 다시 쓴 것이다. 바이트는 다르다.
    tadum 은 거의 같고(저음 66.6→66.0%), gamelan 은 저음이 얇다(24.1→12.2%) —
    타격 네 번(0.22·0.42·0.62·0.88초)과 비배음 구조는 같다.
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


def make_gamelan(out_wav):
    """가믈란 — 인도네시아. 낮은 공 위에 쇠막대를 잇달아 친다.

    가믈란이 가믈란인 이유는 두 가지다.
      ① **비배음** — 청동 막대·공의 부분음은 정수배가 아니다(x2.76, x8.02, x12.16 …).
         정수배로 만들면 그냥 오르간 소리가 난다.
      ② **겹쳐 치기** — 한 번이 아니라 잇달아 치고, 앞 소리가 죽기 전에 다음이 얹힌다.
         0.22·0.42·0.62·0.88초에 넷을 더 얹는다.

    낮은 울림(hum)을 따로 깐 이유: 실제 공은 때린 뒤에도 낮은 소리가 오래 남는다.
    때리는 봉우리를 키우지 않으면서 저음만 채워야 막대 타격이 묻히지 않는다.
    """
    rng = np.random.default_rng(19)
    dur = 2.0
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)

    def strike(at, f0, amp, decay, partials):
        """한 번 때린 소리를 at 초 위치에 얹는다. 높은 부분음일수록 빨리 죽는다."""
        i0 = int(at * SR)
        m = n - i0
        if m <= 0:
            return
        tt = np.arange(m) / SR
        v = np.zeros(m)
        for mul, a in partials:
            v += a * np.sin(2 * np.pi * f0 * mul * tt + rng.uniform(0, 6.28)) \
                 * np.exp(-tt * decay * mul ** 0.35)
        v += rng.normal(0, 1, m) * np.exp(-tt * 160) * 0.12      # 때리는 순간
        v *= np.minimum(1, tt / 0.002)
        out[i0:] += v * amp

    # 낮은 공
    strike(0.00, 62, 3.0, 0.15,
           [(1.00, 1.00), (2.76, 0.34), (5.40, 0.20), (8.02, 0.26),
            (9.21, 0.14), (12.16, 0.11), (22.12, 0.06), (33.56, 0.02)])

    # 쇠막대 — 슬렌드로풍 네 음(정수비가 아니다). 짧고 세게 쳐야 또렷하다.
    for at, f0 in ((0.22, 497), (0.42, 571), (0.62, 754), (0.88, 335)):
        strike(at, f0, 4.5, 16.0,
               [(1.00, 1.00), (2.39, 0.42), (4.61, 0.22), (7.13, 0.10)])

    # 오래 남는 낮은 울림
    out += (np.sin(2 * np.pi * 62 * t)
            + 0.7 * np.sin(2 * np.pi * 93.5 * t + 1.1)) * np.exp(-t * 0.8) * 1.1

    out /= np.max(np.abs(out)) + 1e-9
    out *= 0.82
    f = int(0.35 * SR)
    out[-f:] *= np.cos(np.linspace(0, np.pi / 2, f)) ** 1.5
    write_wav(out_wav, out)


def make_tadum(out_wav):
    """중립음 — '두둥'. 나라를 특정하지 않는 낮은 두 번.

    악기를 흉내 내지 않는다. 낮은 기음(78Hz)에 배음을 조금 얹고 두 번 친다 —
    첫 번째가 크고, 0.34초 뒤 두 번째가 받는다.
    """
    rng = np.random.default_rng(31)
    dur = 2.0
    n = int(dur * SR)
    out = np.zeros(n)

    def hit(at, amp, f0=78.0):
        i0 = int(at * SR)
        m = n - i0
        if m <= 0:
            return
        tt = np.arange(m) / SR
        # 때린 직후 음이 살짝 떨어진다 — 북 가죽이 늘어지는 느낌
        f = f0 * (1 + 0.22 * np.exp(-tt * 26))
        ph = 2 * np.pi * np.cumsum(f) / SR
        v = np.sin(ph) * np.exp(-tt * 3.0)
        v += 0.34 * np.sin(2 * ph) * np.exp(-tt * 5.2)
        v += 0.16 * np.sin(3 * ph) * np.exp(-tt * 7.4)
        v += 0.09 * np.sin(2 * np.pi * 490 * tt) * np.exp(-tt * 12)
        v += rng.normal(0, 1, m) * np.exp(-tt * 120) * 0.10
        v *= np.minimum(1, tt / 0.002)
        out[i0:] += v * amp

    hit(0.00, 1.00)
    hit(0.34, 0.72)

    out /= np.max(np.abs(out)) + 1e-9
    out *= 0.84
    f = int(0.4 * SR)
    out[-f:] *= np.cos(np.linspace(0, np.pi / 2, f)) ** 1.5
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


# 배포된 파일과 바이트까지 같아야 하는 것들
EXACT = {"gong.mp3", "door-creak2.mp3"}


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="intro/ 를 덮어쓴다(기본은 확인만)")
    args = ap.parse_args()
    args.check = not args.write

    tmp = os.path.join(INTRO, ".make_tmp")
    os.makedirs(tmp, exist_ok=True)
    made = {}

    for name, fn, br in (("gong", make_gong, "112k"),
                         ("gamelan", make_gamelan, "112k"),
                         ("tadum", make_tadum, "112k")):
        w = os.path.join(tmp, name + ".wav")
        fn(w)
        encode(w, os.path.join(tmp, name + ".mp3"), br)
        made[name + ".mp3"] = os.path.join(tmp, name + ".mp3")

    if make_door(os.path.join(tmp, "door-creak2.mp3")):
        made["door-creak2.mp3"] = os.path.join(tmp, "door-creak2.mp3")

    bad = 0
    for name, new in made.items():
        cur = os.path.join(INTRO, name)
        if args.check:
            if not os.path.exists(cur):
                print("  %-18s 기존 파일 없음" % name); bad += 1; continue
            same = sha(cur) == sha(new)
            note = "" if name in EXACT else "  ← 특성만 재현(바이트는 원래 다르다)"
            print("  %-18s %s  (기존 %s · 새로 %s)%s" %
                  (name, "같음" if same else "다름", sha(cur), sha(new), note))
            if not same and name in EXACT:
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
