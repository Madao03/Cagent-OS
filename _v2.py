MOJI = ["鍒", "閸", "鎭", "鈺", "鈥", "婊", "鐧", "浣", "鏄"]
for f in ["roadmap.html", "feedback.html", "about.html", "knowledge.html", "chat.html"]:
    p = "src/cagent_os/interfaces/http/static/pages/" + f
    d = open(p, encoding="utf-8").read()
    hits = [c for c in MOJI if c in d]
    print(f, "clean" if not hits else f"MOJIBAKE {hits[:3]}")
