import os

root = r"C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125\dist\languages"
for p in ["de.ts", "fr.ts", "ja_JP.ts", "zh_TW.ts", "zh_CN.ts", "ko_KR.ts"]:
    t = open(os.path.join(root, p), encoding="utf-8").read()
    print(
        "%-10s msgs=%5d unfinished=%4d vanished=%3d bytes=%d"
        % (p, t.count("<message>"), t.count("unfinished"), t.count("vanished"), len(t))
    )
