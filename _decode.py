"""Decode GBK mojibake: the chars shown in the error, back to original UTF-8."""
moji = "鎭愯椽鎸囨暟"
try:
    raw = moji.encode("gbk")  # get the GBK bytes these chars represent
    print("GBK bytes:", raw.hex())
    print("as UTF-8 :", raw.decode("utf-8", errors="replace"))
except Exception as e:
    print("encode fail:", e)

# also try the other variant from the server file earlier
moji2 = "閸掑洦宕插ǎ杈濡€崇础"
try:
    raw2 = moji2.encode("gbk", errors="replace")
    print("\nvariant2 bytes:", raw2.hex())
except Exception as e:
    print("v2 fail:", e)
