"""Print text context around keywords in an HTML file. Usage: ctx.py FILE KW [KW...]"""
import sys, re, html as H
s = open(sys.argv[1], encoding='utf-8', errors='replace').read()
t = ' '.join(H.unescape(re.sub(r'(?is)<script.*?</script>|<style.*?</style>|<[^>]+>', ' ', s)).split())
print('chars', len(t))
for k in sys.argv[2:]:
    for i, m in enumerate(re.finditer(k, t, re.I)):
        if i >= 3: break
        print(f'[{k}]', t[max(0, m.start()-200):m.start()+300])
