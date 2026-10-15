import io
import re
src = r'C:\yt-dlp\yt-dlp-woojini\cookies-screat.txt'
dst = r'C:\yt-dlp\yt-dlp-woojini\app\youtube_cookies.txt'
kept = []
with io.open(src, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        s = line.rstrip('\n')
        if s.startswith('#') or not s.strip():
            if s.startswith('# Netscape') or s.startswith('# http') or s.startswith('# This is'):
                kept.append(s)
            continue
        parts = s.split('\t')
        if len(parts) < 7:
            continue
        dom = parts[0].lower()
        if dom == 'youtube.com' or dom.endswith('.youtube.com') or dom == '.google.com':
            kept.append(s)

header = ['# Netscape HTTP Cookie File', '# This is a generated file!  Do not edit.', '']
body = [l for l in kept if not l.startswith('#')]
with io.open(dst, 'w', encoding='utf-8', newline='\n') as f:
    f.write('\n'.join(header + body) + '\n')

txt = io.open(dst, encoding='utf-8').read()
yt = sum(1 for l in body if '.youtube.com' in l or l.startswith('youtube.com'))
print('Done extracting to', dst)
print('Total data lines:', len(body), '| youtube.com related:', yt)
present = [n for n in ['SID','HSID','SSID','APISID','SAPISID','__Secure-1PSID','__Secure-3PSID','LOGIN_INFO'] if re.search(r'\b'+re.escape(n)+r'\b', txt)]
print('Core auth cookies:', '/'.join(present), f'({len(present)}/8)')
