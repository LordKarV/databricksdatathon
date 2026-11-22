"""sim/policies_baseline.py: nearest, nearest + call first, best on paper (#92)."""
from geo.travel import estimate
from sim import policies_baseline as pb
from sim import world

CTX = pb.context()
CASES = world.cases(5, n=3).to_dict("records")


def test_nearest_is_sorted_listed_and_capped():
    for c in CASES:
        st = pb.nearest(c, CTX)
        lst = CTX["listing"][c["service"]].set_index("unique_id")
        assert 1 <= len(st) <= pb.N_STEPS and all(s["facility_id"] in lst.index for s in st)
        mins = [estimate((c["lat"], c["lon"]), tuple(lst.loc[s["facility_id"], ["lat", "lon"]]), c["state"])["minutes"]
                for s in st]
        assert mins == sorted(mins) and not any(s["call_first"] for s in st)
        cf = pb.nearest_call_first(c, CTX)
        assert [s["facility_id"] for s in cf] == [s["facility_id"] for s in st] and all(s["call_first"] for s in cf)


def test_best_on_paper_is_the_top_p_in_the_state():
    for c in CASES:
        st = pb.best_on_paper(c, CTX)
        lst = CTX["listing"][c["service"]]
        top = lst[lst.state == c["state"]].nlargest(pb.N_STEPS, "p")
        assert {s["facility_id"] for s in st} == set(top.unique_id) or len(set(top.p)) < len(top)
        assert st == pb.best_on_paper(c, CTX)
