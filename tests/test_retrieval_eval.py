import json

from um.bench.retrieval_eval import evaluate


def bench(root):
    (root / "profile" / "topics").mkdir(parents=True)
    (root / "profile" / "profile.md").write_text("---\nname: profile\n---\n- [stated] Name: Sam\n")
    (root / "profile" / "topics" / "music.md").write_text(
        "---\nname: music\ndescription: Sam's instruments\n---\n- [stated] Practice mandolin nicknamed Kestrel\n")
    (root / "profile" / "topics" / "dev.md").write_text(
        "---\nname: dev\ndescription: machine setup\n---\n- [stated] Scratch git branches are prefixed heron-\n")
    qs = [{"id": "a", "split": "dev", "kind": "direct", "question": "What is my practice mandolin's nickname?",
           "answer_terms": ["Kestrel"], "file": "topics/music.md"},
          {"id": "b", "split": "dev", "kind": "paraphrase", "question": "What do I call my small eight-string?",
           "answer_terms": ["Kestrel"], "file": "topics/music.md"},
          {"id": "c", "split": "test", "kind": "direct", "question": "What prefix do my scratch git branches use?",
           "answer_terms": ["heron"], "file": "topics/dev.md"}]
    (root / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))
    (root / "offtopic.jsonl").write_text(json.dumps({"id": "o1", "split": "dev", "prompt": "rename this variable"}) + "\n" +
                                         json.dumps({"id": "o2", "split": "dev", "prompt": "delete my scratch git branches"}) + "\n" +
                                         json.dumps({"id": "o3", "split": "test", "prompt": "list my scratch git branches"}) + "\n")
    return root


def test_word_overlap_hits_direct_and_misses_paraphrase(tmp_path):
    r = evaluate(bench(tmp_path), split="dev")
    assert r["n"] == 2 and r["recall"] == 0.5
    assert r["by_kind"] == {"direct": 1.0, "paraphrase": 0.0}
    assert r["misses"] == ["b"]


def scratchy(profile, prompt):  # a stub retriever: fires on one word, so these tests don't depend on the hook's tuning
    return [("- [stated] Scratch git branches are prefixed heron-", "topics/dev.md")] if "scratch" in prompt else []


def test_offtopic_injection_is_the_share_of_offtopic_prompts_given_any_line(tmp_path):
    r = evaluate(bench(tmp_path), retriever=scratchy, split="dev")
    assert r["offtopic_n"] == 2 and r["offtopic_injection_rate"] == 0.5 and r["offtopic_injected"] == ["o2"]


def test_split_and_custom_retriever(tmp_path):
    root = bench(tmp_path)
    everything = lambda profile, prompt: [("- [stated] Practice mandolin nicknamed Kestrel", "topics/music.md")]
    r = evaluate(root, retriever=everything, split="dev")
    assert r["recall"] == 1.0 and r["offtopic_injection_rate"] == 1.0
    assert evaluate(root, split="test")["n"] == 1


def test_reports_size_and_latency(tmp_path):
    r = evaluate(bench(tmp_path), split="dev")
    assert r["mean_chars"] > 0 and r["p95_ms"] >= 0


def test_offtopic_prompts_are_split_like_the_questions(tmp_path):
    r = evaluate(bench(tmp_path), retriever=scratchy, split="test")
    assert r["offtopic_n"] == 1 and r["offtopic_injected"] == ["o3"]
