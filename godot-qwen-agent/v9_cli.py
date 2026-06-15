"""V9.2 CLI — 复用 app.boot() 共享心脏，零硬编码。"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Load .env
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


async def main():
    # ── 共享心脏：app.boot() ──
    from app import boot

    harness, telemetry, event_bridge = boot()
    print("[CLI] V9.2 Harness via shared bootloader")

    # started flag for telemetry lifecycle
    telemetry_started = False

    # ── Telemetry 启动 ──
    await telemetry.start()
    telemetry_started = True

    print("输入 'quit' 退出\n")

    # ── CLI 主循环 ──
    while True:
        try:
            text = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("quit", "exit", "q"):
            break

        print("Agent: ", end="", flush=True)
        resp = await harness.step(text)
        safe_content = resp.content.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(safe_content)
        print(f"  [gate={resp.metadata.get('gate', '?')}]  "
              f"[track={resp.metadata.get('track', '?')}]")
        print()

    if telemetry_started:
        await telemetry.stop()
    print("再见。")


if __name__ == "__main__":
    asyncio.run(main())
