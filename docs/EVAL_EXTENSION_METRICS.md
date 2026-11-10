# Retrieval metrics: current scope

`retrieval_metrics` implements only known-citation hit and recall for an explicitly supplied relevance set. These are proxies because known citations are not an exhaustive set of relevant passages. Its denominator is the number of distinct supplied supporting record IDs. F3 population counts and F6 scoped unanswerability are marked not applicable to passage recall. This function is a primitive; qrels generation, retrieval experiments, other metrics, uncertainty intervals, human relevance labels and plots remain unimplemented. No evaluation has been run.
