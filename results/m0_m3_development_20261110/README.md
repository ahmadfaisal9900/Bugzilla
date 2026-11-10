# M0 and M3 development results

These files are exact copies of the saved outputs from 10 November 2026.
All methods used the same 34 development questions. M0 and M3 used Qwen 2.5
1.5B on CPU. The direct SQL check used the same database as M3.

| Method | Correct |
|---|---:|
| M0 | 7/34 |
| M3 with the model | 27/34 |
| Direct SQL check | 28/34 |

M0's seven correct responses were all unknown answers. Both M3 versions
missed six questions requiring developer comments. The model also chose an
invalid lookup for the reopened count of bug 1718774.

- [M0 answers](m0.predictions.jsonl) and [scores](m0.scores.jsonl)
- [M3 answers](m3.predictions.jsonl) and [scores](m3.scores.jsonl)
- [Direct SQL scores](sql_control.scores.jsonl)
- [Five new practice questions and their answers](new_practice_questions.json)

The five new questions are separate from the 34 questions above. Their
answers passed database checks. These are development results against the
current answer key, which includes optional rows awaiting human review.

Each answer and score has a question ID for matching it to the review sheet.
The commands are in [the methods guide](../../docs/PHASE06_METHODS.md).
