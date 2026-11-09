# M0 and M3 trial results

These files are exact copies of the saved outputs from 6 November 2026.

M0 and M3 answered the same five questions using Qwen 2.5 1.5B on CPU.
M0 scored 0/5, including one timeout. M3 scored 4/5 and matched the direct
SQL check. Two of the quiz answers were still provisional.

- [M0 answers](m0.predictions.jsonl) and [scores](m0.scores.jsonl)
- [M3 answers](m3.predictions.jsonl) and [scores](m3.scores.jsonl)
- [Direct SQL scores](sql_control.scores.jsonl)
- [Five new practice questions and their answers](new_practice_questions.json)

The new questions are separate from the five questions used above. Their
answers were checked against the database. The model trial used the original
quiz questions.

Each answer and score has a question ID for matching it to the review sheet.
The database bundle is required to repeat the SQL run. The commands are in
[the methods guide](../../docs/PHASE06_METHODS.md).
