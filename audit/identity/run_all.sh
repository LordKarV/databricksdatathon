#!/bin/sh
# Re-run the identity audit end to end (local snapshot only, no warehouse queries).
set -e
cd "$(dirname "$0")"
PY=../../.venv/bin/python
$PY q5_cluster.py > out_q5.txt
$PY q1_duplicates.py > out_q1.txt
$PY q1b_missed.py > out_q1b.txt
$PY eval_dup_rules.py > out_eval_dup.txt
$PY q3_contacts.py > out_q3.txt
$PY q3b_shared_phone_source.py > out_q3b.txt
$PY -W ignore q2_chains.py > out_q2.txt
$PY q4_existence.py > out_q4.txt
$PY q4b_phone_split.py > out_q4c.txt
$PY dump_groups.py grp_strong 47 1 > out/hand_strong_all.txt
$PY q4c_counts.py > out_q4d.txt
