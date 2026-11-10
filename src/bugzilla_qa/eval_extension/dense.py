"""Local batched embedding shards and FAISS cosine index; never calls a hosted API."""
import json
import os
from pathlib import Path

from bugzilla_qa.eval_extension.cli import file_hash
from bugzilla_qa.eval_extension.retrieval import BUG_ID, rrf


def _deps():
    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer
        from tqdm import tqdm
    except ImportError as exc:
        raise RuntimeError('Dense retrieval requires requirements-eval-extension.txt: ' + str(exc)) from exc
    return faiss, np, SentenceTransformer, tqdm


def read_docs(corpus):
    with Path(corpus).open(encoding='utf-8') as f:
        return [json.loads(line) for line in f]


def build_dense(corpus, directory, model_name, batch_size=32, device='cpu', resume=False):
    faiss, np, SentenceTransformer, tqdm = _deps()
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    docs = read_docs(corpus)
    corpus_hash = file_hash(Path(corpus))
    manifest_path = directory / 'dense_manifest.json'
    index_path = directory / 'dense.faiss'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if (not resume or manifest['corpus_sha256'] != corpus_hash or manifest['model'] != model_name
                or manifest.get('code_sha256') != file_hash(Path(__file__))):
            raise RuntimeError('existing dense index has different identity or --resume was not given')
        if not index_path.exists() or file_hash(index_path) != manifest['index_sha256']:
            raise RuntimeError('dense index hash mismatch')
        return manifest
    model = SentenceTransformer(model_name, device=device)
    revision = getattr(model[0].auto_model.config, '_commit_hash', None)
    if not revision:
        raise RuntimeError('model revision could not be identified; use a pinned cached Hugging Face model')
    shard_dir = directory / 'dense_shards'; shard_dir.mkdir(exist_ok=True)
    identity = {'model':model_name, 'revision':revision, 'corpus_sha256':corpus_hash, 'batch_size':batch_size,
                'code_sha256':file_hash(Path(__file__))}
    marker = shard_dir / 'identity.json'
    if marker.exists() and json.loads(marker.read_text()) != identity:
        raise RuntimeError('dense shard identity mismatch; choose another output root')
    marker.write_text(json.dumps(identity, sort_keys=True))
    dimension = model.get_sentence_embedding_dimension()
    index = faiss.IndexFlatIP(dimension)
    truncated = 0
    for start in tqdm(range(0, len(docs), batch_size), desc='Embedding batches', unit='batch'):
        shard = shard_dir / ('%09d.npy' % start)
        checksum = shard.with_suffix('.sha256')
        expected = min(batch_size, len(docs)-start)
        lengths=model.tokenizer([d['text'] for d in docs[start:start+batch_size]], truncation=False,
                                add_special_tokens=True, return_length=True)['length']
        truncated += sum(length > model.max_seq_length for length in lengths)
        if shard.exists() and resume:
            if not checksum.exists() or checksum.read_text().strip() != file_hash(shard):
                raise RuntimeError('dense shard checksum mismatch: '+str(shard))
            vectors = np.load(str(shard), allow_pickle=False)
            if vectors.shape != (expected, dimension) or not np.isfinite(vectors).all():
                raise RuntimeError('invalid dense shard ' + str(shard))
        else:
            vectors = model.encode([d['text'] for d in docs[start:start+batch_size]], batch_size=batch_size,
                                   normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
            vectors = np.asarray(vectors, dtype='float32')
            tmp = str(shard) + '.tmp'
            with open(tmp, 'wb') as f: np.save(f, vectors, allow_pickle=False)
            os.replace(tmp, str(shard))
            checksum.write_text(file_hash(shard)+'\n')
        index.add(np.ascontiguousarray(vectors, dtype='float32'))
    temp = str(index_path) + '.tmp'
    faiss.write_index(index, temp); os.replace(temp, str(index_path))
    manifest = dict(identity, state='COMPLETE', count=len(docs), dimension=dimension,
                    index_sha256=file_hash(index_path), tokenizer_max_tokens=model.max_seq_length,
                    truncated_chunks=truncated,
                    truncation='chunks exceeding model tokenizer maximum are truncated by the embedding model')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


class DenseSearcher:
    def __init__(self, corpus, directory, model_name, device='cpu'):
        faiss, np, SentenceTransformer, _ = _deps()
        self.np = np; self.docs = read_docs(corpus); directory = Path(directory)
        manifest = json.loads((directory / 'dense_manifest.json').read_text())
        if manifest['model'] != model_name or manifest['corpus_sha256'] != file_hash(Path(corpus)):
            raise RuntimeError('dense model/corpus mismatch')
        if file_hash(directory / 'dense.faiss') != manifest['index_sha256']:
            raise RuntimeError('dense index hash mismatch')
        self.index = faiss.read_index(str(directory / 'dense.faiss'))
        self.model = SentenceTransformer(model_name, device=device, revision=manifest['revision'])
        if self.index.ntotal != len(self.docs):
            raise RuntimeError('dense mapping length mismatch')

    def search(self, query, k=5, filter_bug=True):
        match = BUG_ID.search(query) if filter_bug else None
        allowed = [i for i, d in enumerate(self.docs) if not match or d['bug_id'] == match.group(1)]
        if not allowed:
            return []
        vec = self.np.asarray(self.model.encode([query], normalize_embeddings=True, convert_to_numpy=True), dtype='float32')
        # Search all on explicit-ID queries so filtering cannot lose a valid matching bug.
        n = len(self.docs) if match else min(len(self.docs), k)
        scores, indices = self.index.search(vec, n)
        selected = [(int(i), float(s)) for i,s in zip(indices[0],scores[0]) if i >= 0 and (not match or self.docs[int(i)]['bug_id'] == match.group(1))]
        selected.sort(key=lambda x:(-x[1],self.docs[x[0]]['chunk_id']))
        return [dict(self.docs[i], rank=rank, score=score) for rank,(i,score) in enumerate(selected[:k],1)]


def rerank(query, hits, model, top_k=5):
    if not hits:
        return []
    scores = model.predict([(query, h['text']) for h in hits], show_progress_bar=False)
    ordered = sorted(zip(hits, scores), key=lambda x:(-float(x[1]), x[0]['chunk_id']))[:top_k]
    return [dict(hit, rank=i, score=float(score), reranker_score=float(score)) for i,(hit,score) in enumerate(ordered,1)]


def hierarchical(query, flat_hits, lexical_hits, k=5, max_bugs=5):
    """Rank parent bugs from metadata hits, then choose their highest-ranked passages."""
    parents = []
    for hit in lexical_hits + flat_hits:
        if hit['kind'] == 'metadata' and hit['bug_id'] not in parents:
            parents.append(hit['bug_id'])
    parents = parents[:max_bugs]
    allowed = set(parents)
    return [dict(hit, rank=i, stage1_bug_ids=parents) for i,hit in enumerate(
            [h for h in flat_hits if h['bug_id'] in allowed][:k],1)]
