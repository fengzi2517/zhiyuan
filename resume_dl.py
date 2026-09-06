# 临时脚本：Range 断点续传 bge-m3 pytorch_model.bin（完成后删除）
import requests, time, os

url = 'https://hf-mirror.com/BAAI/bge-m3/resolve/main/pytorch_model.bin'
inc = r'D:\Users\3392\Desktop\jl\rag-app\.hf-cache\hub\models--BAAI--bge-m3\blobs\b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38.7b6c2724.incomplete'
total = 2271145830
MB = 1024 * 1024

pos = os.path.getsize(inc)
print(f'start: {pos // MB}MB / {total // MB}MB', flush=True)
for attempt in range(30):
    if pos >= total:
        break
    try:
        r = requests.get(url, headers={'Range': f'bytes={pos}-'},
                         stream=True, timeout=60, allow_redirects=True)
        if r.status_code not in (200, 206):
            raise RuntimeError(f'HTTP {r.status_code}')
        with open(inc, 'ab') as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                pos += len(chunk)
                if pos % (100 * MB) < (1 << 20):
                    print(f'{pos // MB}MB', flush=True)
    except Exception as e:
        print(f'retry {attempt}: {e}', flush=True)
        time.sleep(3)

size = os.path.getsize(inc)
print(f'final: {size} expect: {total}', flush=True)
print('COMPLETE' if size == total else 'INCOMPLETE', flush=True)
