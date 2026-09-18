"""把私有笔记加密成 data/private.enc.json —— 密文入库，明文永不进公开仓库。

背景
----
公开站点托管在 GitHub Pages，而 Pages 只能服务 public 仓库，所以公开库的
所有文件（含 data/*.json）任何人都能下载。私有笔记要能在线上看，又不能在
线上被公开读到，就只能加密：

    knowledge/_private/*.md  (本机明文，.gitignore)
        ↓ build_knowledge.py
    data/knowledge.local.json (本机明文全量索引，.gitignore)
        ↓ 本脚本加密
    data/private.enc.json     (只有密文，提交进公开库 → 线上可下载但读不懂)

浏览器端用 WebCrypto 做同一套算法（PBKDF2-HMAC-SHA256 + AES-256-GCM）解密，
算法参数写在密文文件头部，前端照着读。

安全性说明（重要）
------------------
密文是公开可下载的，**密码强度就是全部安全性**。任何人拿到密文都可以离线
暴力破解，所以口令必须足够强（建议 4 个以上随机词，或 16 位以上随机串）。
用 `--gen` 可以让脚本生成一个足够强的口令。

用法
----
    python scripts/build_private_bundle.py --gen          # 生成强口令并加密
    python scripts/build_private_bundle.py                # 用 config/private.key 里的口令加密
    python scripts/build_private_bundle.py --passphrase X  # 直接指定口令
    python scripts/build_private_bundle.py --check        # 只显示会加密多少篇，不写文件

口令来源优先级：--passphrase > 环境变量 WORKBUDDY_PASSPHRASE > config/private.key
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
LOCAL_KB = ROOT / "data" / "knowledge.local.json"
OUT_PATH = ROOT / "data" / "private.enc.json"
KEY_FILE = ROOT / "config" / "private.key"

# 私有笔记在 knowledge.local.json 里的 id 前缀（见 build_knowledge.py 的 note id 规则）
PRIVATE_PREFIX = "_private/"

ITERATIONS = 600_000          # PBKDF2 迭代次数：浏览器端约 0.3-1s，足够拖慢暴力破解
CST = timezone(timedelta(hours=8))

# 口令用词表：形象、好记、拼写简单，避免同音歧义。
# 词表大小直接决定口令强度（每词约 log2(N) 比特），所以不能太短。
_RAW_WORDS = """
harbor lantern meadow cobalt ember willow compass granite jasmine tundra
saffron orbit puzzle velvet cedar marble falcon ripple thistle quartz nimbus
sable topaz wander bamboo crater dune fable garnet hollow ivory jubilee
anchor ballot canyon dagger easel fathom gable heron inlet jigsaw kettle lagoon
magnet nectar oasis pebble quiver rafter saddle tassel urchin vulture walnut
yonder zephyr almond breeze cinder dapple elm forest gadget hammock icicle
jackal kelp lilac mitten nutmeg onyx parcel quill riddle syrup trellis
ukulele vertex wagon xenon yawn zinnia apricot badge cactus dolphin
echo fringe glacier helmet insect jungle kernel lobster monsoon noodle
octopus penguin quokka rabbit sparrow turtle umbrella village
xylophone yacht zebra acorn butter candle domino eggplant feather guitar
hazel iceberg jellyfish kiwi lemonade muffin notebook oyster parsley quicksand
ribbon sunflower teapot unicorn violin watermelon yarrow zucchini banjo
dew drop flint glade hive iris juniper knot lotus maple
noble olive petal reef shore timber utter vivid whisk yolk
"""
WORDS = sorted(set(_RAW_WORDS.split()))

# 5 词 × 约 2^7.2 词表 ≈ 2^36 ... 所以用 6 词（约 2^43）配合 60 万次 PBKDF2，
# 单张高端 GPU 穷举需数十年量级。
WORD_COUNT = 6


def gen_passphrase(n: int = WORD_COUNT) -> str:
    """生成 n 个随机词组成口令。"""
    return "-".join(secrets.choice(WORDS) for _ in range(n))


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def get_passphrase(args) -> str:
    if args.passphrase:
        return args.passphrase
    env = os.environ.get("WORKBUDDY_PASSPHRASE")
    if env:
        return env
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="加密私有笔记为 data/private.enc.json")
    ap.add_argument("--passphrase", default=None, help="加密口令")
    ap.add_argument("--gen", action="store_true", help="生成强口令，写入 config/private.key 并加密")
    ap.add_argument("--check", action="store_true", help="只统计，不写文件")
    args = ap.parse_args()

    if not LOCAL_KB.exists():
        print(f"找不到 {LOCAL_KB.relative_to(ROOT)}，请先运行 python scripts/build_knowledge.py")
        return 1

    kb = json.loads(LOCAL_KB.read_text(encoding="utf-8"))
    private_notes = [n for n in kb.get("notes", []) if n["id"].startswith(PRIVATE_PREFIX)]
    if not private_notes:
        print("没有找到私有笔记（knowledge/_private/ 为空？）")
        print("提示：先跑 python scripts/sync_private.py 从私有库拉取。")
        return 1

    print(f"待加密私有笔记 {len(private_notes)} 篇：")
    for n in private_notes:
        print(f"  · {n['title']}  ({n.get('word_count', '?')} 字, {len(n.get('keywords', []))} 关键词)")

    if args.check:
        print("\n--check 模式，未写文件")
        return 0

    if args.gen:
        pw = gen_passphrase()
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(pw, encoding="utf-8")
        print(f"\n已生成口令并写入 {KEY_FILE.relative_to(ROOT)}（该文件已被 .gitignore 排除）")
        args.passphrase = pw
    else:
        pw = get_passphrase(args)

    if not pw:
        print("\n没有可用口令。请用 --gen 生成，或把口令写进 config/private.key")
        return 1
    if len(pw) < 12:
        print(f"\n口令只有 {len(pw)} 位，太短了。密文是公开可下载的，口令强度就是全部安全性。")
        return 1

    payload = {
        "v": 1,
        "generated_at": datetime.now(CST).replace(microsecond=0).isoformat(),
        "notes": private_notes,
    }
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    key = kdf.derive(pw.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, plaintext, None)

    out = {
        "_comment": "私有笔记密文。明文只在本机，本文件可安全提交到公开仓库。",
        "v": 1,
        "alg": "AES-256-GCM",
        "kdf": {"name": "PBKDF2", "hash": "SHA-256", "iterations": ITERATIONS, "salt": b64(salt)},
        "iv": b64(iv),
        "ct": b64(ct),
        "note_count": len(private_notes),
        "generated_at": payload["generated_at"],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n已写出 {OUT_PATH.relative_to(ROOT)}")
    print(f"  明文 {len(plaintext):,} 字节 → 密文 {len(ct):,} 字节（含 {ITERATIONS:,} 次 PBKDF2）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
