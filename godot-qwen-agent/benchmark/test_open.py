# test_open.py
try:
    with open(r"G:\rag666\config.json", "r", encoding="utf-8") as f:
        print("✅ open() 成功！")
        print(f.read()[:100])
except Exception as e:
    print("❌ open() 失败:", e)