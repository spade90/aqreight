import argparse
import json
from urllib import request


QUESTIONS = [
    {
        "name": "damaged blender",
        "query": "Can a customer return a damaged blender after 20 days?",
        "expected_titles": ["Returns_and_Refunds.md", "Warranty_Policy.md"],
    },
    {
        "name": "east malaysia shipping",
        "query": "What’s the shipping SLA to East Malaysia for bulky items?",
        "expected_titles": ["Delivery_and_Shipping.md"],
    },
]


def post_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Run a small RAG smoke evaluation.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    ingest_result = post_json(f"{args.base_url}/api/ingest")
    results = []
    passed = True

    for case in QUESTIONS:
        payload = post_json(f"{args.base_url}/api/ask", {"query": case["query"], "k": 4})
        cited_titles = [citation["title"] for citation in payload.get("citations", [])]
        missing = [title for title in case["expected_titles"] if title not in cited_titles]
        ok = not missing
        passed = passed and ok
        results.append(
            {
                "name": case["name"],
                "query": case["query"],
                "ok": ok,
                "expected_titles": case["expected_titles"],
                "cited_titles": cited_titles,
                "missing_titles": missing,
            }
        )

    report = {
        "ingest": ingest_result,
        "passed": passed,
        "results": results,
    }

    if args.as_json:
        print(json.dumps(report, indent=2))
        return

    print("Smoke Eval")
    print(f"- Ingested docs: {ingest_result['indexed_docs']}")
    print(f"- Ingested chunks: {ingest_result['indexed_chunks']}")
    for result in results:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"- {status}: {result['name']}")
        print(f"  Query: {result['query']}")
        print(f"  Cited: {', '.join(result['cited_titles']) or '(none)'}")
        if result["missing_titles"]:
            print(f"  Missing: {', '.join(result['missing_titles'])}")

    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
