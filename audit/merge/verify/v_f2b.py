"""F2 gap probe: near-spelling foreign names found by my rule but not by the finder (finder classes many as 'self'
through its same-first-letter fuzzy match). Prints a seeded sample of 15 records."""
import contextlib, io, os
import pandas as pd
with contextlib.redirect_stdout(io.StringIO()):
    import v_f2
nn, ids, rec = v_f2.nn, set(v_f2.ids), v_f2.rec
mo = nn[(nn.ratio >= 75) & ~nn.unique_id.isin(ids)]
print("mine-only near-name records", mo.unique_id.nunique(), "; same first letter as record's distinctive name:",
      mo.assign(fl=[m[:1].lower() == rec.name[u][:1].lower() for u, m in zip(mo.unique_id, mo.mention)]).groupby("unique_id").fl.any().sum())
x = mo.drop_duplicates("unique_id").sample(15, random_state=8)
pd.set_option("display.width", 300); pd.set_option("display.max_colwidth", 150)
print(x.assign(rn=x.unique_id.map(rec.name), city=x.unique_id.map(rec.address_city))[["rn", "city", "mention", "ratio", "text"]].to_string())
