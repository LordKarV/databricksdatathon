# Demo narration (3 minutes, about 420 words)

For the human narrator. Values in [brackets] are read off the stills in `demo/out/shots/` on the day; none is
typed in advance, because the data and the model change. Times match `demo/STORYBOARD.md`.

**0:00 open.** "An ASHA worker in Sitamarhi, Bihar has a patient whose clinic note says dialysis. Cheap phone,
one bar of signal. For this recording we set the phone's GPS to Singwahini village. The app fills in where she
is by itself."

**0:15 plan.** "She taps dialysis. The app gives a first choice and two backups, and says CALL FIRST. Each card
says how sure we are in words: not verified, call to confirm. Each one quotes the sentence from the
facility's own listing, with its id, and the travel time as a range: about [low]-[high] minutes."

**0:35 why_not (if shown).** "Why not the nearer ones? [Name] is closer, but its dialysis sentence names a
different hospital, so we ignore it and say so."

**0:45 why.** "Why this one? Here is the evidence word for word, and how often listings like this checked out:
[track record line]. 'How we decided' breaks the score into points, and they add up to the score. The app
checks every number on this screen against the data before release."

**1:10 call.** "Before travelling she calls. The app tells her what to ask, and why. They have no slot today.
She taps 'Said no', and that goes on the slip."

**1:20 slip.** "The backup said yes, so she makes a referral slip: where to go, phone, travel, and the made time.
There's no patient name and no decimals. It goes by SMS or WhatsApp."

**1:35 route.** "Some emergencies need two stops. For an accident, the app plans a route: first care at [stop 1]
within [limit] minutes, then definitive care at [stop 2]. Every stop shows its chance and the evidence behind
it, and what going straight there would cost: [direct] against [route]."

**2:00 offline.** "Now there's no internet. Same tap, same answer, from the facility data saved on the phone on
[date]. Calls use the SIM, so the call button still works."

**2:20 area.** "For a block health officer: trauma near the NH-19 at Mohania. The app does not pretend. It shows
how much of the area has confirmed care, how much a few phone calls could add, and where there's no public
evidence of care at all. Then the ten calls that would close most of the gap."

**2:40 how.** "How good is it? We say so plainly. [Number] of [number] map points were more than 50 km from their
own PIN code. Here is our score against simple baselines, including an LLM judge, and a list of what did not
work."

**2:50 stories, close.** "[One line per data story.] Every answer shows its evidence, how sure we are, and the
one call to make."
